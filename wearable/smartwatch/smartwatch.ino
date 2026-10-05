// ====== Orologio dell'operatore - Nano ESP32 + MAX30100 (v5) ======
// LCD 16x2:   RS=D7, EN=D8, D4..D7 = A0..A3 (RW a GND)
// MAX30100:   VIN=3V3, GND, SDA=A4, SCL=A5
// Attuatori:  vibrazione D2, pulsante D3 (verso GND), LED blu D4, verde D5, rosso D6
// DA CONTROLLARE: i numeri di pin qui sopra sono quelli "di progetto" nel
// codice - vanno confermati uno per uno con il collegamento reale sulla
// breadboard (vedi discussione separata sul cablaggio) prima di fidarsene.
//
// ATTENZIONE HARDWARE: il motore di vibrazione NON va collegato direttamente
// al pin D2. Serve un transistor NPN (es. BC547/2N2222) pilotato dal pin,
// con un diodo flyback in parallelo al motore.
//
// ====================================================================
// NOVITA' v5 - AUTOMA A STATI FINITI FORMALIZZATO (nomenclatura z0..z6)
// ====================================================================
//
// STATI:
//   z0 STATE_MISSION_NOT_STARTED - connesso (o in attesa di esserlo) al CC, la
//      missione non e' ancora iniziata. Il ciclo di monitoraggio non e'
//      attivo; l'LCD mostra lo stato del collegamento. Una pressione breve
//      del pulsante accende qui la PROVA DEL SENSORE biometrico: l'LCD
//      mostra battito e saturazione, o "Appoggia il dito" in attesa della
//      lettura, esattamente come in missione, senza bisogno del drone ne'
//      della rete (la prova ha la precedenza anche su "Connessione persa").
//      Una seconda pressione breve la spegne, e l'avvio della missione la
//      chiude da se'. L'automa resta comunque in z0: le soglie non vengono
//      valutate e nessun allarme biometrico parte verso il CC.
//   z1 STATE_SEARCHING_SIGNAL - missione attiva, sensore non ancora agganciato.
//   z2 STATE_NORMAL - lettura valida, parametri nella norma.
//   z3 STATE_VERIFYING - condizione critica rilevata, in attesa di conferma
//      (persistenza).
//   z4 STATE_ALARM - almeno una causa di allarme e' attiva (vedi sotto).
//   z5 STATE_SILENCED - notifica sospesa dall'operatore, le cause restano
//      tracciate in sottofondo.
//   z6 STATE_FAULT - il sensore non risponde sul bus I2C, anche se si
//      stacca a orologio acceso (controllato ogni 2 secondi). Se
//      all'accensione il sensore non risponde dopo tutti i tentativi, si
//      parte da qui anche senza missione e ci si resta finche' non risponde.
//
// z0 E IL BYPASS PER I TEST DA BANCO:
//   In funzionamento reale, il dispositivo resta in z0 finche' non riceve
//   dal CC un messaggio {"tipo":"AVVIO_MISSIONE"} (evento "a"). Il drone lo
//   pubblica al decollo e pubblica {"tipo":"FINE_MISSIONE"} a qualunque
//   atterraggio; entrambi restano sul broker (retain), quindi l'orologio li
//   riceve anche se si collega a volo gia' iniziato. All'avvio e alla fine
//   della missione l'LCD mostra per qualche secondo "Missione avviata" /
//   "Missione terminata", con il LED blu fisso e un breve colpo di vibrazione.
//   Se il collegamento al broker, una volta stabilito, cade per almeno 15
//   secondi, l'LCD mostra fisso "Connessione persa" finche' non torna, con o
//   senza missione: senza rete l'orologio non riceve gli allarmi del drone.
//   Un allarme ha comunque la precedenza su questa schermata.
//   Per i test senza il drone, la costante BYPASS_MISSION_WAIT piu' sotto,
//   se messa a true, salta z0, fa partire il dispositivo direttamente in z1
//   e ignora la fine missione. IMPORTANTE: ricordarsi di rimetterla a false
//   prima del funzionamento reale sul campo.
//
// PERSISTENZA DELLA MISSIONE ATTRAVERSO UN RESET (evento "r"):
//   Un doppio-lungo-premi sul pulsante riavvia il chip (ESP.restart()),
//   che cancellerebbe normalmente ogni variabile in RAM, incluso lo stato
//   "missione attiva". Per evitare di dover re-inviare "AVVIO_MISSIONE"
//   dopo ogni reset del solo orologio (la missione, gestita dal drone,
//   prosegue indipendentemente), lo stato "missione attiva" viene salvato
//   nella memoria non volatile (libreria Preferences) e riletto al boot:
//   se era true, il dispositivo salta z0 e riparte da z1 (o z6, se il
//   sensore risulta assente), senza attendere una nuova "a".
//
// STATE_ALARM (z4) A PIU' CAUSE INDIPENDENTI:
//   z4 puo' essere determinato da tre cause indipendenti, tracciate
//   separatamente (biometricCauseActive, ppeCauseActive,
//   restrictedAreaCauseActive):
//     - biometricCauseActive: confermata localmente dopo la persistenza in z3
//       (evento s4), si azzera quando i parametri rientrano secondo le
//       soglie di uscita (evento s5). In questo caso, e SOLO in questo
//       caso, l'orologio informa il CC (azione p).
//     - ppeCauseActive / restrictedAreaCauseActive: impostate a true alla
//       ricezione di un messaggio {"tipo":"DPI_MANCANTE"} (evento w1) /
//       {"tipo":"AREA_VIETATA"} dal CC, azzerate alla ricezione del
//       corrispondente messaggio di risoluzione ({"tipo":"DPI_OK"} /
//       {"tipo":"AREA_OK"}).
//   Le protezioni collettive (DPC) non arrivano all'orologio: una rete
//   mancante e' un problema del cantiere, non dell'operatore, e resta solo
//   nel Log degli alert del drone.
//   Lo stato resta STATE_ALARM finche' ALMENO UNA causa e' attiva; si esce
//   (evento s5, generalizzato) solo quando NESSUNA causa e' piu' attiva.
//   Se l'operatore silenzia (evento m) mentre piu' cause sono attive, e ne
//   arriva una NUOVA (non un rinnovo di una gia' presente), l'allarme si
//   riattiva subito, scavalcando il silenziamento - nessuna causa nuova
//   resta nascosta. Uscita/ingresso sono valutati ad ogni ciclo, quindi
//   nessuna causa puo' "perdersi". Il canale dal CC porta SOLO messaggi di
//   allarme riconosciuti (DPI mancante, area vietata e relative risoluzioni,
//   oltre ad avvio/fine missione): qualunque altro "tipo" ricevuto viene
//   scartato (solo loggato su seriale), non genera alcuna notifica.
//   NOTA: il monitoraggio biometrico resta attivo anche mentre z4/z5 sono
//   gia' in corso per un'altra causa. Il controllo scritto in z2/z3 li' non
//   verrebbe eseguito, quindi un cronometro dedicato (maskedCriticalPending in
//   updateFsm) ripete la stessa valutazione con la stessa persistenza:
//   l'evento s4 puo' quindi scattare anche da z4/z5. Serve perche' il
//   pericolo biometrico e' il piu' grave, e senza questo sarebbe l'unico
//   che un allarme minore riesce a nascondere.
//
// EVENTI s5 vs u (rientro dei parametri, due soglie distinte):
//   u  - "uscita da verifica": prima della conferma dell'allarme (z3), se
//        il parametro rientra sotto le STESSE soglie usate per rilevarne
//        il superamento (s3), si torna subito a z2. Rientro "veloce".
//   s5 - "rientro/risoluzione": usato per uscire da z4/z5. Per la causa
//        biometrica, richiede le soglie di uscita (piu' restrittive di
//        quelle di attivazione - isteresi vera). Per le cause DPI e area
//        vietata, equivale alla ricezione del messaggio di risoluzione dal CC.
//        z4/z5 -> z2 solo quando TUTTE le cause attive sono rientrate.
//
// PULSANTE (unico comando, il RESET della scheda non e' accessibile a
// contenitore chiuso):
//   - pressione BREVE          -> silenzia l'allarme (evento m); fuori
//                                 missione accende o spegne la prova del
//                                 sensore biometrico (vedi z0 qui sopra)
//   - DUE pressioni LUNGHE     -> riavvio del dispositivo (evento r)
//
// NOMENCLATURA EVENTI ALLINEATA AGLI ALTRI AUTOMI DEL SISTEMA (drone/CC):
//   a coincide con "Decollo" del drone. w1 e' la ricezione di un allarme DPI
//   dal CC (generato tipicamente durante una sosta di supervisione del
//   drone, tra i suoi eventi c e d); l'evento w2 (allarme DPC) non riguarda
//   piu' l'orologio. fm/fa/fc sono i tre distinti modi in cui il drone puo'
//   atterrare (manuale/automatico/critico per batteria): tutti e tre, per
//   l'orologio, valgono come fine missione.
//
// MONITOR SERIALE (115200 baud): un evento per riga, con il tipo fra
// parentesi quadre ([AVVIO], [RETE], [DRONE], [STATO], [ALLARME], [AVVISO],
// [PULSANTE], [SENSORE]). I valori per il Plotter seriale si attivano con
// SERIAL_PLOTTER.
// Librerie: MAX30100_milan (gabriel-milan, derivata da MAX30100lib),
// PubSubClient (knolleary), Preferences (inclusa nel core ESP32 di Arduino)

#include <Wire.h> //il protocollo del sensore
#include <LiquidCrystal.h> //per comunicare con LCD
#include "MAX30100_PulseOximeter.h" //libreria del sensore biometrico
#include <WiFi.h> //libreria per la connessione wi-fi
#include <PubSubClient.h> //libreria per protocollo MQTT
#include <lwip/sockets.h> //select() sul socket del broker, per sapere se c'e' posto per scrivere
#include <Preferences.h> //Libreria per scrivere o leggere dati nella memoria permanente della scheda (sopravvive ai riavvii)

// ---------- Test da banco senza drone ----------
// true  = salta z0 e parte direttamente in ricerca segnale (comodo per i
//         test in laboratorio, senza far decollare il drone)
// false = comportamento reale: resta in z0 finche' il drone non decolla
const bool BYPASS_MISSION_WAIT = false;

// ---------- Monitor seriale ----------
// true  = stampa 4 volte al secondo battito e saturazione, grezzi e filtrati,
//         da disegnare con Strumenti -> Plotter seriale
// false = il monitor seriale mostra solo gli eventi, uno per riga
const bool SERIAL_PLOTTER = false;

// ---------- LCD ----------
const int LCD_RS = 7, LCD_EN = 8, LCD_D4 = A0, LCD_D5 = A1, LCD_D6 = A2, LCD_D7 = A3;
LiquidCrystal lcd(LCD_RS, LCD_EN, LCD_D4, LCD_D5, LCD_D6, LCD_D7);

// ---------- Attuatori e pulsante ----------
const int PIN_VIBRATION = 2;
const int PIN_BUTTON    = 3;
const int PIN_LED_BLUE  = 4;
const int PIN_LED_GREEN = 5;
const int PIN_LED_RED   = 6;

// ---------- Sensore ----------
PulseOximeter pox;

const LEDCurrent IR_LED_CURRENT = MAX30100_LED_CURR_14_2MA;

bool sensorPresent = false; // il sensore risponde correttamente?
const int SENSOR_MAX_ATTEMPTS = 10; // quante volte riprovare ad agganciare il sensore all'accensione
const unsigned long SENSOR_RETRY_INTERVAL_MS = 5000; // ogni quanto riprovare in sottofondo se manca
unsigned long lastSensorRetryMs = 0; // un "segnaposto" che ricorda quando è stato fatto l'ultimo tentativo.
// Controllo periodico del sensore gia' agganciato: un filo staccato a
// orologio acceso non blocca la libreria, che continua a leggere valori a vuoto.
const unsigned long SENSOR_CHECK_INTERVAL_MS = 2000; // ogni quanto interrogare il sensore
const int SENSOR_MAX_MISSED_CHECKS = 2; // controlli falliti di fila prima di darlo per perso
unsigned long lastSensorCheckMs = 0;
int missedSensorChecks = 0;

// ---------- Persistenza missione (sopravvive a un reset) ----------
Preferences prefs; // oggetto che verrà utilizzato per accedere alla memoria permanente
// Missione in corso. Di solito equivale a "stato diverso da z0", ma senza
// sensore l'orologio resta in z6 anche fuori missione.
bool missionActive = false;

// ---------- Prova del sensore fuori missione ----------
// Acceso dal pulsante in z0: fa mostrare sull'LCD la lettura biometrica anche
// senza missione e senza rete, per controllare il sensore al banco o a inizio
// turno. Non e' uno stato dell'automa e non sposta 'currentState': il sensore
// e' gia' campionato dal loop() in ogni stato, qui cambia solo cosa si vede.
bool sensorTestActive = false;

// ---------- Rete e canale MQTT ----------
// Rete WiFi e indirizzo del broker si impostano in network_config.h
// (WIFI_SSID, WIFI_PASS, MQTT_BROKER_IP).
#include "network_config.h"
const int   MQTT_PORT   = 1883;
// Il sistema ha un solo orologio, quindi un solo operatore: l'identificativo
// non serve a distinguere i dispositivi, ma entra nei topic MQTT e il drone
// lo legge da li' per etichettare telemetria e allarmi biometrici.
const char* WORKER_ID   = "operaio_1";

WiFiClient   wifiClient;  // connessione di rete "grezza"
PubSubClient mqtt(wifiClient);  // livello sopra che parla il protocollo MQTT usando quella connessione

String telemetryTopic;  // riempito in setup(), dipende da WORKER_ID
String presenceTopic;   // riempito in setup(), dipende da WORKER_ID
const char* ALARM_TOPIC = "cantiere/allarmi";  // canale su cui l'orologio riceve i messaggi del drone

const unsigned long PUBLISH_INTERVAL_MS       = 500; // Ogni quanto inviare la telemetria
const unsigned long NETWORK_RETRY_INTERVAL_MS = 5000;// Ogni quanto ritentare la connessione se caduta
// Tempo concesso a un tentativo WiFi (aggancio al router e assegnazione
// dell'indirizzo) prima di ricominciarlo: con un router lento un nuovo
// WiFi.begin() ogni NETWORK_RETRY_INTERVAL_MS interromperebbe ogni tentativo a metà.
const unsigned long WIFI_CONNECT_TIMEOUT_MS = 20000;
unsigned long lastPublishMs      = 0; // due "orologi interni" che ricordano
unsigned long lastNetworkRetryMs = 0; // l'ultima volta che ciascuna delle due cose è successa
unsigned long wifiAttemptStartMs = 0;   // quando è partito l'ultimo WiFi.begin()
bool          wifiAttemptStarted = false;
// Una caduta del collegamento al broker viene segnalata sull'LCD solo se dura
// almeno NETWORK_LOSS_GRACE_MS: quelle di un istante si risolvono al tentativo
// successivo e un avviso sarebbe solo fastidioso.
const unsigned long NETWORK_LOSS_GRACE_MS = 15000;
bool          brokerWasConnected  = false;  // collegamento al broker al giro precedente
bool          brokerEverConnected = false;  // broker collegato almeno una volta dall'accensione
unsigned long brokerLostSinceMs   = 0;      // da quando il broker non risponde
bool          networkReportedDown = true;   // rete data per assente sull'LCD (all'accensione non e' ancora collegata)

// Il collegamento al broker gira in un task FreeRTOS a parte: mqtt.connect()
// aspetta fino a 3 s il PC e fino a 2 s la risposta, e intanto il loop deve
// continuare a leggere il sensore, il pulsante e a muovere la vibrazione.
// Finche' il task lavora, il loop non tocca mqtt.
String        mqttClientId;                     // riempito in setup(), dipende da WORKER_ID
volatile bool brokerConnectRunning  = false;    // task di collegamento in corso
volatile bool brokerConnectFinished = false;    // il task ha finito, esito da raccogliere
volatile bool brokerConnectOk       = false;    // esito dell'ultimo tentativo
// Se il PC sparisce senza chiudere la connessione, il buffer di invio si
// riempie e ogni scrittura fermerebbe il loop fino a 10 s: si scrive solo se
// c'e' posto, e una connessione che non accetta dati per BROKER_STALL_MS si chiude.
const unsigned long BROKER_STALL_MS = 5000;
unsigned long brokerWritableSinceMs = 0;        // ultima volta in cui si poteva scrivere

// Allarme biometrico (azione p) in attesa di essere consegnato al drone: se
// scatta a rete caduta parte appena il broker torna, invece di andare perso.
bool biometricAlarmPending = false;
int  pendingAlarmBpm  = 0;
int  pendingAlarmSpo2 = 0;

// ---------- Cause di allarme (z4) ----------
// I tre "interruttori" indipendenti che, combinati, decidono se lo stato
// deve essere STATE_ALARM: basta che uno solo sia vero.
bool biometricCauseActive = false;
bool ppeCauseActive = false;
bool restrictedAreaCauseActive = false;  // persona in area vietata, segnalata dal drone
bool isAnyCauseActive() { return biometricCauseActive || ppeCauseActive || restrictedAreaCauseActive; } // true se almeno una causa è attiva

// Elenco dei DPI mancanti inviato dal drone (es. "Elmetto, Gilet"): serve
// solo per l'LCD, l'allarme resta una causa sola.
String missingPpeList = "";

// ---------- Visualizzazione delle cause sull'LCD ----------
// Identificativi usati solo per decidere cosa scrivere sul display.
const int CAUSE_NONE            = -1;
const int CAUSE_BIOMETRIC       = 0;
const int CAUSE_RESTRICTED_AREA = 1;
const int CAUSE_PPE             = 2;

const unsigned int  LCD_COLUMNS           = 16;
const unsigned long CAUSE_ROTATION_MS     = 4000;  // con piu' allarmi insieme, quanto resta a schermo ciascuno
const unsigned long SCROLL_STEP_MS        = 450;   // ogni quanto scorre di un carattere un testo troppo lungo
const unsigned long SCROLL_START_PAUSE_MS = 1500; // quanto resta fermo l'inizio del testo prima di scorrere

// ---------- Ritmi della vibrazione ----------
// Il ritmo segue la causa mostrata sull'LCD, cosi' l'operatore distingue al
// polso di che allarme si tratta senza guardare: continua per il pericolo
// medico, battiti ravvicinati per l'area vietata, un colpo ogni tanto per i
// DPI, che sono un richiamo e non un'emergenza immediata.
const unsigned long AREA_VIBRATION_ON_MS     = 250;
const unsigned long AREA_VIBRATION_PERIOD_MS = 500;
const unsigned long PPE_VIBRATION_ON_MS      = 300;
const unsigned long PPE_VIBRATION_PERIOD_MS  = 1500;

// Da quando e' a schermo la causa attuale: lo scorrimento riparte da capo a
// ogni cambio di causa, altrimenti l'elenco ricomparirebbe a meta' parola.
int displayedCause = CAUSE_NONE;
unsigned long displayedCauseSinceMs = 0;
int prevCauseMask = 0;  // quali cause erano attive al giro precedente

// La vibrazione NON segue il testo a schermo ma la causa piu' grave attiva:
// leggere richiede tempo e le schermate si alternano, mentre il polso deve
// dire sempre qual e' il pericolo peggiore, anche mentre si legge un altro.
int vibrationCause = CAUSE_NONE;
unsigned long vibrationCauseSinceMs = 0;

// ---------- Avvisi temporanei ----------
// Per qualche secondo dopo il decollo o l'atterraggio del drone l'LCD lo dice
// su entrambe le righe e il LED blu resta acceso fisso. Un allarme che arriva
// nel frattempo lo scavalca subito.
const unsigned long NOTICE_MS = 3000;
const char*   noticeLine1   = nullptr;  // nullptr = nessun avviso mostrato finora
const char*   noticeLine2   = "";
unsigned long noticeStartMs = 0;

// ---------- Soglie con ISTERESI ----------
// I limiti che, se superati, fanno scattare la condizione critica 

// soglie "di ingresso" nell'allarme
const int BPM_MIN_IN  = 30;
const int BPM_MAX_IN  = 120;
const int SPO2_MIN_IN = 92;
// soglie "di uscita" nell'allarme (più strette: isteresi, evita lo sfarfallio)
const int BPM_MIN_OUT  = 55;
const int BPM_MAX_OUT  = 115;
const int SPO2_MIN_OUT = 94;

// ---------- Temporizzazioni della FSM ----------
const unsigned long PERSISTENCE_MS        = 3000; // quanto deve durare una condizione critica prima di essere confermata (evento s4)
const unsigned long SILENCE_TIMEOUT_MS    = 30000; // quanto dura al massimo un silenziamento prima di riattivarsi da solo (evento t)
const unsigned long HR_STALE_TIMEOUT_MS   = 5000; //Se non arriva nessun battito per 5 secondi, la lettura (battito e SpO2) viene considerata non più valida

// ---------- Macchina a stati ----------
// Corrispondenza con la nomenclatura dell'automa: z0=STATE_MISSION_NOT_STARTED,
// z1=STATE_SEARCHING_SIGNAL, z2=STATE_NORMAL, z3=STATE_VERIFYING,
// z4=STATE_ALARM, z5=STATE_SILENCED, z6=STATE_FAULT
enum FsmState {
  STATE_MISSION_NOT_STARTED,
  STATE_SEARCHING_SIGNAL,
  STATE_NORMAL,
  STATE_VERIFYING,
  STATE_ALARM,
  STATE_SILENCED,
  STATE_FAULT
};

FsmState currentState = STATE_MISSION_NOT_STARTED; // la variabile più importante: dice "dove si trova" il dispositivo nell'automa
// Ultimo stato scritto sul monitor seriale: logStateChange() stampa ogni cambio.
FsmState    loggedState     = STATE_MISSION_NOT_STARTED;
const char* loggedStateName = "";
// Due "cronometri": memorizzano quando (in millisecondi 
//dall'accensione) si è entrati in STATE_VERIFYING o in STATE_SILENCED, 
//per poter calcolare dopo quanto tempo è trascorso.
unsigned long verifyStartMs  = 0;
unsigned long silenceStartMs  = 0;

// Persistenza della condizione critica quando l'automa si trova gia' in
// z4/z5 per un'altra causa: li' non passa piu' da z2/z3, dove il controllo
// biometrico e' scritto, e serve un cronometro dedicato.
bool maskedCriticalPending = false;
unsigned long maskedCriticalStartMs = 0;

// ---------- Evento battito ----------
bool          newBeat = false;  // scritta dalla callback qui sotto, durante pox.update()
unsigned long lastBeatMs = 0;   // memorizza quando è arrivato l'ultimo battito reale

// Questa funzione non la chiamiamo mai noi direttamente nel codice
// — viene chiamata automaticamente dalla libreria del sensore ogni 
// volta che rileva un battito vero
void onBeatDetected() {
  lastBeatMs = millis();
  newBeat = true;
}

// ---------- Parametri di filtraggio ----------
// Quanti campioni tiene in memoria ciascuna delle due 
// "finestre mobili" su cui calcoliamo la mediana
const int   HR_MEDIAN_WINDOW   = 5;
const int   SPO2_MEDIAN_WINDOW = 5;
// I coefficienti della media mobile esponenziale (EMA): 
//  un numero tra 0 e 1 che decide "quanto peso" dare al nuovo campione
// rispetto alla storia precedente
const float HR_EMA_ALPHA   = 0.35;
const float SPO2_EMA_ALPHA = 0.30;
const float HR_MAX_DEVIATION_RATIO = 0.25; // È la soglia massima di variazione percentuale che un nuovo battito può avere rispetto al valore già filtrato, per essere accettato come "vero".

const int HR_MAX_REJECTIONS = 6; //se vengono scartati 6 battiti di fila, la catena si ri-aggancia da zero
int consecutiveHrRejections = 0; // contatore

const int SPO2_MAX_OUT_OF_RANGE = 2;//analogo a sopra
int consecutiveSpo2OutOfRange = 0;

float hrBuffer[HR_MEDIAN_WINDOW];// array — è la finestra mobile che contiene gli ultimi 5 battiti grezzi, su cui calcoliamo la mediana.
int   hrBufferIndex = 0, hrBufferCount = 0; // ricorda in quale casella dell'array scrivere il prossimo valore - conta quante caselle sono già state riempite almeno una volta

float spo2Buffer[SPO2_MEDIAN_WINDOW]; // analogo a sopra
int   spo2BufferIndex = 0, spo2BufferCount = 0;

float hrFiltered   = 0; // I valori finali, dopo entrambi gli stadi 
float spo2Filtered = 0; // di filtraggio
bool  hrReady   = false; //diventano true solo quando la rispettiva 
bool  spo2Ready = false; // catena si è "agganciata" (almeno 3 campioni validi consecutivi accumulati)

// valori grezzi (prima di qualsiasi filtro, tenuti solo per il debug/telemetria)
float hrRaw   = 0;
float spo2Raw = 0;

int bpm  = 0; //I valori finali arrotondati a numero intero - quelli 
int spo2 = 0; //che effettivamente vengono mostrati sull'LCD e confrontati con le soglie.
bool readingValid = false; // true solo quando entrambe le catene (hrReady e spo2Ready) sono agganciate
// Ultima lettura valida, mostrata dall'allarme biometrico anche quando il
// segnale si perde per un momento
int lastValidBpm  = 0;
int lastValidSpo2 = 0;

// ---------- Timer ----------
// Ogni quanto (in millisecondi) eseguire ciascun compito periodico
const unsigned long SPO2_SAMPLE_INTERVAL_MS    = 1000;
const unsigned long DISPLAY_UPDATE_INTERVAL_MS = 250;
const unsigned long FSM_UPDATE_INTERVAL_MS     = 250;
// Per ciascuno dei tre, memorizza quando è stato eseguito l'ultima volta
unsigned long lastSpo2SampleMs    = 0;
unsigned long lastDisplayUpdateMs = 0;
unsigned long lastFsmUpdateMs     = 0;

// ---------- Gestione pulsante ----------
const unsigned long DEBOUNCE_MS              = 50; // Tempo minimo che un livello del pulsante deve restare stabile prima di essere considerato "vero"
const unsigned long LONG_PRESS_MS            = 2000; // Quanto tenere premuto perché conti come "pressione lunga"
const unsigned long RESET_SEQUENCE_WINDOW_MS = 5000; // Quanto tempo si ha per fare la seconda pressione lunga dopo la prima, prima che la sequenza di reset scada

bool lastRawButtonLevel = HIGH; // L'ultimo livello elettrico letto sul pin del pulsante, "grezzo" (non ancora confermato dal debounce). Parte da HIGH perché a riposo, con INPUT_PULLUP, il pin legge alto.
bool buttonPressed      = false; // Lo stato "vero" del pulsante, dopo il debounce
unsigned long lastLevelChangeMs = 0; // quando è cambiato l'ultima volta il livello grezzo
unsigned long pressStartMs      = 0; // quando è iniziata la pressione corrente
bool longPressCounted    = false; // evita di contare due volte la stessa pressione lunga
int  pendingResetPresses = 0; // 0 = nessuna pressione lunga in sospeso, 1 = ne è già arrivata una, in attesa della seconda
unsigned long lastLongPressEndMs = 0; // quando è finita (rilasciata) l'ultima pressione lunga

// ================== CANALE MQTT ==================
// Da qui in poi iniziano le vere FUNZIONI (non solo dichiarazioni di
// variabili): blocchi di codice riutilizzabile che vengono richiamati per
// nome dal resto del programma.

// Traduce lo stato interno (l'enum FsmState) in una stringa leggibile,
// usata sia per i messaggi di log sul monitor seriale sia per i messaggi
// JSON inviati al CC via MQTT.
// Senza parametro (legge direttamente la variabile globale 'currentState'): un
// parametro di tipo enum qui mandava in confusione il generatore automatico
// di prototipi di Arduino IDE, che generava un prototipo errato prima
// ancora che l'enum FsmState fosse visibile, causando un errore di
// compilazione. Tutte le chiamate nel resto del file usano comunque sempre
// e solo la variabile globale 'currentState', quindi il parametro era superfluo.
// Le stringhe restituite restano in italiano: sono i nomi che il CC riceve
// nel campo "stato" e riconosce (drone/ui/plots/biometric_plots.py).
const char* getStateName() {
  switch (currentState) {
    case STATE_MISSION_NOT_STARTED: return "MISSIONE_NON_AVVIATA";
    case STATE_SEARCHING_SIGNAL:    return "RICERCA_SEGNALE";
    case STATE_VERIFYING:           return "VERIFICA";
    case STATE_ALARM:               return "ALLARME";
    case STATE_SILENCED:            return "SILENZIATO";
    case STATE_FAULT:               return "GUASTO";
    default:                        return "NORMALE";
  }
}

// Scrive in 'dest' il valore con un decimale, oppure "null" se la lettura non
// c'e': cosi' il CC distingue un buco nei dati da un valore davvero zero.
void formatValue(char* dest, size_t size, bool present, float value) {
  if (present) {
    snprintf(dest, size, "%.1f", value);
  } else {
    snprintf(dest, size, "null");
  }
}

// Costruisce un messaggio JSON con i valori correnti (bpm, spo2, stato) e
// lo invia al CC sul topic personale di questo operatore. Chiamata
// periodicamente dal loop(), non solo quando c'è un allarme: è la
// "telemetria continua" che permette al CC di sapere come sta l'operatore
// in ogni momento. Se la lettura non è ancora valida, bpm/spo2 vengono
// inviati come "null" invece di 0, per non far credere al CC che i valori
// siano davvero zero.
// Porta anche i valori grezzi e filtrati con un decimale (hr_grezzo,
// hr_filtrato, spo2_grezzo, spo2_filtrato): il CC li registra e a fine
// sessione ne disegna i grafici di confronto. Un valore che non c'e' (catena
// non agganciata, nessun battito recente, dito assente) viaggia come null.
void publishTelemetry() {
  char hrRawText[12], hrFilteredText[12], spo2RawText[12], spo2FilteredText[12];
  bool recentBeat = (millis() - lastBeatMs <= HR_STALE_TIMEOUT_MS);
  formatValue(hrRawText,        sizeof(hrRawText),        hrRaw > 0 && recentBeat, hrRaw);
  formatValue(hrFilteredText,   sizeof(hrFilteredText),   hrReady,                 hrFiltered);
  formatValue(spo2RawText,      sizeof(spo2RawText),      spo2Raw > 0,             spo2Raw);
  formatValue(spo2FilteredText, sizeof(spo2FilteredText), spo2Ready,               spo2Filtered);

  char rawFilteredFields[112];
  snprintf(rawFilteredFields, sizeof(rawFilteredFields),
           "\"hr_grezzo\":%s,\"hr_filtrato\":%s,\"spo2_grezzo\":%s,\"spo2_filtrato\":%s",
           hrRawText, hrFilteredText, spo2RawText, spo2FilteredText);

  // Il messaggio piu' lungo sta sotto i 200 caratteri: insieme al topic resta
  // entro il buffer di PubSubClient (setBufferSize in setup()).
  char payload[224];  // buffer di testo dove costruiamo il JSON prima di inviarlo
  if (readingValid) {
    snprintf(payload, sizeof(payload),  // compone la stringa in modo sicuro, senza sforare la dimensione del buffer
             "{\"bpm\":%d,\"spo2\":%d,\"stato\":\"%s\",\"lettura_valida\":true,%s}",
             bpm, spo2, getStateName(), rawFilteredFields);
  } else {
    snprintf(payload, sizeof(payload),
             "{\"bpm\":null,\"spo2\":null,\"stato\":\"%s\",\"lettura_valida\":false,%s}",
             getStateName(), rawFilteredFields);
  }
  mqtt.publish(telemetryTopic.c_str(), payload);  // invio effettivo del messaggio sul topic
}

// Evento singolo, inviato una volta all'ingresso in STATE_ALARM per causa
// BIOMETRICA (azione "p"). Le cause DPI e area vietata non generano questo
// evento: il CC gia' sa di aver inviato la segnalazione, non serve
// confermarglielo.
// A differenza di publishTelemetry() (che gira in continuazione), questa
// funzione viene chiamata una volta sola, esattamente nel momento in cui
// scatta l'allarme biometrico - utile al CC per registrare "quando" è
// successo, non solo "come sta ora".
// Qui l'allarme viene solo registrato: lo invia sendPendingBiometricAlarm()
// appena il broker puo' riceverlo, cosi' a rete caduta non va perso.
void publishBiometricAlarm() {
  pendingAlarmBpm  = bpm;
  pendingAlarmSpo2 = spo2;
  biometricAlarmPending = true;
  Serial.print("[ALLARME] valori fuori soglia, BPM ");
  Serial.print(bpm);
  Serial.print(" e SpO2 ");
  Serial.print(spo2);
  Serial.println("%");
}

// Consegna al drone l'allarme biometrico in attesa, se c'e'. Chiamata dal
// loop solo con il broker collegato; se l'invio fallisce si riprova al giro dopo.
void sendPendingBiometricAlarm() {
  if (!biometricAlarmPending) return;
  char payload[160];
  snprintf(payload, sizeof(payload),
           "{\"bpm\":%d,\"spo2\":%d,\"evento\":\"BIOMETRIA_ANOMALA\"}",
           pendingAlarmBpm, pendingAlarmSpo2);
  if (mqtt.publish(telemetryTopic.c_str(), payload)) {
    biometricAlarmPending = false;
    Serial.println("[ALLARME] avviso inviato al drone");
  }
}

// Estrae il valore stringa di un campo JSON semplice, dato il suo nome
// (es. "tipo" o "dettaglio"), senza usare una libreria di parsing JSON vera e
// propria - funziona solo per un formato "piatto" come quello usato qui,
// senza virgolette annidate o caratteri di escape particolari nel valore.
String extractField(const String& msg, const char* fieldName) {
  String key = String("\"") + fieldName + "\"";        // es. "\"tipo\""
  int fieldPos = msg.indexOf(key);                     // cerca il nome del campo nel messaggio
  if (fieldPos < 0) return "";                         // campo assente: nessun valore da estrarre
  int i = msg.indexOf(':', fieldPos);                  // cerca il ":" subito dopo il nome del campo
  if (i < 0) return "";
  i++;
  while (i < (int)msg.length() && msg[i] == ' ') i++;  // salta eventuali spazi dopo il ":"
  if (i < (int)msg.length() && msg[i] == '"') {        // il valore deve iniziare con una virgoletta
    int closingQuotePos = msg.indexOf('"', i + 1);     // cerca la virgoletta di chiusura
    if (closingQuotePos > i) return msg.substring(i + 1, closingQuotePos);  // ritorna il testo tra le due virgolette
  }
  return "";
}

// Funzione richiamata AUTOMATICAMENTE dalla libreria PubSubClient ogni
// volta che arriva un messaggio su un topic a cui siamo iscritti (vedi
// mqtt.subscribe in ensureNetwork() più sotto). È il "centro smistamento"
// di tutto ciò che arriva dal CC: legge il campo "tipo" e decide cosa fare
// in base al suo valore.
void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String msg;
  msg.reserve(length);  // pre-alloca la stringa alla lunghezza giusta, più efficiente
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];  // ricostruisce il testo byte per byte

  String type = extractField(msg, "tipo");
  // Gli allarmi del drone che non riguardano l'orologio (per esempio le
  // cadute) passano sullo stesso canale, ma senza "tipo".
  if (type.length() == 0) {
    Serial.println("[DRONE] allarme non destinato all'orologio, ignorato");
    return;
  }
  String detail = extractField(msg, "dettaglio");
  Serial.print("[DRONE] ");
  Serial.print(type);
  if (detail.length() > 0) {
    Serial.print(" (");
    Serial.print(detail);
    Serial.print(")");
  }
  Serial.println();

  // ---- Avvio / fine missione (eventi a, fm/fa/fc) ----
  // Nota: a = "Decollo" nell'automa del drone, coincide con l'avvio della
  // missione anche per l'orologio. fm/fa/fc sono i tre modi distinti in
  // cui il drone puo' atterrare (manuale, automatico nominale, critico per
  // batteria) - tutti e tre terminano la missione anche per l'orologio,
  // che pero' non ha bisogno di distinguerli: il CC invia comunque un
  // unico messaggio {"tipo":"FINE_MISSIONE"} indipendentemente da quale
  // dei tre ha innescato l'atterraggio.
  if (type == "AVVIO_MISSIONE") {
    prefs.putBool("missione", true);  // salvato in memoria permanente: sopravvive a un reset (r)
    if (!missionActive) {
      missionActive = true;
      sensorTestActive = false;  // da qui in poi vale il monitoraggio vero, non la prova
      if (currentState == STATE_MISSION_NOT_STARTED) {
        currentState = STATE_SEARCHING_SIGNAL;  // z0 -> z1; senza sensore si resta in z6
      }
      showNotice("Missione", "avviata");  // solo all'avvio vero, non a ogni ricollegamento
      pulseVibration(150);
    }
    return;
  }
  if (type == "FINE_MISSIONE") {
    // Nei test da banco il monitoraggio resta sempre attivo: il broker
    // conserva la fine dell'ultima missione e la ripete a ogni collegamento.
    if (BYPASS_MISSION_WAIT) {
      Serial.println("[DRONE] ignorato: test da banco");
      return;
    }
    bool missionWasRunning = missionActive;
    missionActive = false;
    prefs.putBool("missione", false);
    biometricCauseActive = false;  // fine missione: azzera tutte le cause di allarme pendenti
    ppeCauseActive = false;
    missingPpeList = "";
    restrictedAreaCauseActive = false;
    currentState = sensorPresent ? STATE_MISSION_NOT_STARTED : STATE_FAULT;  // torna a z0, o resta in z6 senza sensore
    if (missionWasRunning) {
      showNotice("Missione", "terminata");
      pulseVibration(150);
    }
    return;
  }

  // Senza missione (z0, oppure z6 col sensore assente) l'automa reagisce solo
  // all'avvio della missione (evento a).
  if (!missionActive) {
    Serial.println("[DRONE] ignorato: la missione non e' avviata");
    return;
  }

  // ---- DPI e area vietata (evento w1 e relative risoluzioni) ----
  if (type == "DPI_MANCANTE") {          // evento w1
    bool isNewCause = !ppeCauseActive;   // true solo se la causa NON era già attiva (rinnovo vs novità)
    ppeCauseActive = true;
    missingPpeList = detail;             // quali DPI mancano, per l'LCD
    if (isNewCause) currentState = STATE_ALARM;   // scavalca anche un STATE_SILENCED in corso
    return;
  }
  if (type == "AREA_VIETATA") {          // persona in area vietata
    bool isNewCause = !restrictedAreaCauseActive;
    restrictedAreaCauseActive = true;
    if (isNewCause) currentState = STATE_ALARM;
    return;
  }
  if (type == "AREA_OK") { restrictedAreaCauseActive = false; return; }   // area di nuovo libera
  if (type == "DPI_OK") { ppeCauseActive = false; missingPpeList = ""; return; }  // risoluzione: contribuisce a s5

  // ---- Qualunque altro "tipo" viene scartato ----
  Serial.println("[DRONE] tipo sconosciuto, ignorato");
}

// Task del collegamento al broker (vedi brokerConnectRunning): fa solo
// mqtt.connect(), l'esito lo raccoglie il loop con finishBrokerConnect().
// Il quarto/quinto/sesto parametro configurano il "Last Will and
// Testament": se l'orologio si disconnette in modo anomalo, il broker
// pubblica automaticamente "offline" sul topic di presenza, così il CC
// se ne accorge anche senza un messaggio esplicito dell'orologio.
// L'ultimo (false) chiede una sessione persistente: mentre l'orologio e'
// scollegato, per una caduta di rete o un riavvio, il broker conserva i
// messaggi del drone (QoS 1) e li consegna al ricollegamento, nell'ordine
// in cui sono partiti. Senza, un DPI_OK o un AREA_OK inviato a rete
// caduta andrebbe perso e l'allarme resterebbe acceso. Il broker
// riconosce la sessione da mqttClientId, che quindi non deve cambiare.
void brokerConnectTask(void*) {
  brokerConnectOk = mqtt.connect(mqttClientId.c_str(), NULL, NULL,
                                 presenceTopic.c_str(), 1, true, "offline", false);
  brokerConnectFinished = true;
  vTaskDelete(NULL);
}

// Raccoglie l'esito del task di collegamento, quando ha finito: da qui mqtt
// torna al loop.
void finishBrokerConnect() {
  if (!brokerConnectRunning || !brokerConnectFinished) return;
  brokerConnectRunning = false;
  if (brokerConnectOk) {
    mqtt.publish(presenceTopic.c_str(), "online", true);
    mqtt.subscribe(ALARM_TOPIC, 1);  // da qui in poi riceveremo i messaggi del CC su questo topic
    brokerWritableSinceMs = millis();
    Serial.println("[RETE] broker collegato, in ascolto dei messaggi del drone");
  } else {
    Serial.print("[RETE] Connessione ");
    Serial.print(describeBrokerStatus());
    Serial.print(" (codice ");
    Serial.print(mqtt.state());
    Serial.println(")");
  }
}

// true se la connessione al broker ha posto per altri dati: scrivere quando e'
// piena fermerebbe il loop (vedi BROKER_STALL_MS). Il controllo non aspetta.
bool isBrokerWritable() {
  int fd = wifiClient.fd();
  if (fd < 0) return false;
  fd_set writeSet;
  FD_ZERO(&writeSet);
  FD_SET(fd, &writeSet);
  struct timeval noWait = {0, 0};
  return select(fd + 1, NULL, &writeSet, NULL, &noWait) > 0;
}

// Gestisce la connessione di rete "a piccoli passi", senza mai bloccare il
// resto del programma: se il WiFi non è connesso, avvia il tentativo (non
// bloccante) e ritorna subito; solo se il WiFi è già su, prova anche MQTT,
// in un task a parte (brokerConnectTask).
// Viene richiamata periodicamente dal loop() quando la connessione manca.
void ensureNetwork() {
  if (WiFi.status() != WL_CONNECTED) {
    // Un tentativo ancora nei tempi si lascia concludere: lo stato 0 indica
    // che l'aggancio al router è riuscito e si attende solo l'indirizzo IP.
    if (wifiAttemptStarted && millis() - wifiAttemptStartMs < WIFI_CONNECT_TIMEOUT_MS) {
      Serial.print("[RETE] Connessione ");
      Serial.print(describeWifiStatus());
      Serial.print(" (stato ");
      Serial.print(WiFi.status());
      Serial.println(")");
      return;
    }
    Serial.print("[RETE] collego il WiFi ");
    Serial.println(WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    wifiAttemptStartMs = millis();
    wifiAttemptStarted = true;
    return;
  }
  if (!mqtt.connected()) {
    Serial.print("[RETE] WiFi collegato, IP orologio ");
    Serial.print(WiFi.localIP());
    Serial.print(". Collego il broker ");
    Serial.println(MQTT_BROKER_IP);
    brokerConnectFinished = false;
    brokerConnectRunning  = true;
    // Sul core 0, con lo stack WiFi: il core 1 resta tutto al loop.
    if (xTaskCreatePinnedToCore(brokerConnectTask, "broker", 6144, NULL, 1, NULL, 0) != pdPASS) {
      brokerConnectRunning = false;
      Serial.println("[RETE] collegamento al broker non avviato: memoria insufficiente");
    }
  }
}

// ================== SETUP ==================

// Raggruppa la configurazione del sensore, usata sia al primo aggancio in
// setup() sia nei ritentativi in background (retrySensorIfMissing()) -
// evita di duplicare le stesse tre righe in due punti diversi.
void configureSensor() {
  pox.setIRLedCurrent(IR_LED_CURRENT);
  pox.setOnBeatDetectedCallback(onBeatDetected);  // da qui in poi onBeatDetected() verrà chiamata automaticamente
  sensorPresent = true;
}

// Eseguita UNA SOLA VOLTA all'accensione/reset del dispositivo. Prepara
// tutto ciò che serve prima che il loop() principale inizi a girare.
void setup() {
  Serial.begin(115200);  // apre la porta seriale per log/telemetria verso il PC
  Serial.println();
  Serial.print("[AVVIO] Work Guardian, orologio ");
  Serial.println(WORKER_ID);

  telemetryTopic = String("cantiere/sensori/orologio/") + WORKER_ID;  // costruisce i nomi dei topic ora che WORKER_ID è noto
  presenceTopic  = String("cantiere/sistema/orologio_") + WORKER_ID + "/status";
  mqttClientId   = String("wg-orologio_") + WORKER_ID;
  WiFi.mode(WIFI_STA);  // modalità "stazione": si collega a una rete esistente, non ne crea una propria
  // Il core ESP32 rifiuta di default le reti protette con una sicurezza inferiore
  // a WPA2, mentre il router del laboratorio offre solo WPA-PSK (TKIP).
  WiFi.setMinSecurity(WIFI_AUTH_WPA_PSK);
  mqtt.setServer(MQTT_BROKER_IP, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);  // registra la funzione da chiamare quando arriva un messaggio
  mqtt.setSocketTimeout(2);  // secondi massimi di attesa su operazioni di rete, per non bloccare troppo a lungo
  // Un messaggio piu' lungo del buffer viene scartato senza conferma e, con la
  // sessione persistente, il broker lo rimanderebbe a ogni ricollegamento: il
  // doppio dei 256 byte predefiniti lascia margine agli allarmi del drone.
  mqtt.setBufferSize(512);

  pinMode(PIN_VIBRATION, OUTPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);  // pull-up interno: il pin legge HIGH a riposo, LOW quando premuto
  pinMode(PIN_LED_BLUE, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);

  lcd.begin(16, 2);
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Work Guardian");  // schermata di benvenuto, solo estetica
  delay(1500);
  lcd.clear();

  // Stato di riposo iniziale degli attuatori, prima ancora di sapere se il
  // sensore risponde: vibrazione spenta, LED verde acceso "di default".
  digitalWrite(PIN_VIBRATION, LOW);
  digitalWrite(PIN_LED_BLUE, LOW);
  digitalWrite(PIN_LED_GREEN, HIGH);
  digitalWrite(PIN_LED_RED, LOW);

  // Prova ad agganciare il sensore fino a SENSOR_MAX_ATTEMPTS volte,
  // aspettando 2 secondi tra un tentativo e l'altro. Il ciclo non e'
  // infinito: se il sensore continua a non rispondere, si esce comunque
  // dopo i tentativi previsti e ci riprova retrySensorIfMissing().
  int attempts = 0;
  while (attempts < SENSOR_MAX_ATTEMPTS) {
    if (pox.begin()) {
      configureSensor();
      break;  // aggancio riuscito, esce subito dal ciclo
    }
    attempts++;
    lcd.setCursor(0, 0);
    lcd.print("Sensore assente");
    lcd.setCursor(0, 1);
    lcd.print("Tentativo:");
    lcd.print(attempts);
    lcd.print("/");
    lcd.print(SENSOR_MAX_ATTEMPTS);
    Serial.print("[SENSORE] non risponde, tentativo ");
    Serial.print(attempts);
    Serial.print("/");
    Serial.println(SENSOR_MAX_ATTEMPTS);
    digitalWrite(PIN_LED_RED, HIGH);
    digitalWrite(PIN_LED_GREEN, LOW);
    delay(2000);
  }

  lcd.clear();

  // ---- Missione: persistenza attraverso i reset (r) ----
  prefs.begin("orologio", false);  // apre lo spazio di memoria permanente chiamato "orologio"
  bool missionWasActive = prefs.getBool("missione", false);  // valore salvato, o false se non esiste ancora
  missionActive = BYPASS_MISSION_WAIT || missionWasActive;

  // Decide lo stato di partenza. Se il sensore non ha risposto a nessun
  // tentativo si parte da STATE_FAULT, con o senza missione: l'orologio non
  // deve sembrare pronto. Altrimenti, in modalità test (bypass) o con la
  // missione già attiva prima di un eventuale reset, si salta z0 e si parte
  // dalla ricerca del segnale; se no si resta in attesa dell'avvio missione.
  // LCD e LED dello stato scelto li imposta il loop() al primo aggiornamento.
  if (!sensorPresent) {
    currentState = STATE_FAULT;
  } else if (missionActive) {
    currentState = STATE_SEARCHING_SIGNAL;
  } else {
    currentState = STATE_MISSION_NOT_STARTED;
  }

  if (sensorPresent) {
    Serial.println("[SENSORE] pronto");
  } else {
    Serial.print("[SENSORE] assente, riprovo ogni ");
    Serial.print(SENSOR_RETRY_INTERVAL_MS / 1000);
    Serial.println(" s");
  }
  Serial.print("[STATO] iniziale ");
  Serial.print(getStateName());
  if (BYPASS_MISSION_WAIT) {
    Serial.println(" (test da banco: attesa missione saltata)");
  } else if (missionWasActive) {
    Serial.println(" (missione ripresa dopo un riavvio)");
  } else {
    Serial.println();
  }
  loggedState = currentState;
  loggedStateName = getStateName();

  // Inizializza tutti i "cronometri" al tempo corrente, così i primi
  // controlli nel loop() non scattano immediatamente per un falso timeout.
  unsigned long nowMs = millis();
  lastSpo2SampleMs = lastDisplayUpdateMs = lastFsmUpdateMs = nowMs;
  lastBeatMs = nowMs;
  lastSensorRetryMs = lastSensorCheckMs = nowMs;
}

// ================== LOOP ==================

// Il cuore pulsante del programma: gira all'infinito, migliaia di volte al
// secondo. Ogni "compito" al suo interno è temporizzato in modo indipendente
// (chi ogni ciclo, chi solo ogni tot millisecondi), per tenere il sistema
// reattivo senza sprecare risorse a fare tutto in continuazione.
void loop() {
  if (sensorPresent) {
    pox.update();  // interroga il sensore; se c'è un nuovo battito, scatena onBeatDetected() internamente
  }

  handleButton();  // controllato ad OGNI ciclo: serve massima reattività per il debounce

  checkSensorConnection(); // se il sensore agganciato smette di rispondere, lo da' per perso
  retrySensorIfMissing();  // no-op se il sensore è già presente, altrimenti prova a riagganciarlo ogni tanto

  unsigned long nowMs = millis();

  if (sensorPresent) {
    if (newBeat) {
      newBeat = false;
      sampleHr();  // elabora il nuovo battito solo quando ce n'è uno vero
    }

    if (hrReady && (nowMs - lastBeatMs > HR_STALE_TIMEOUT_MS)) {
      resetHr();  // troppo silenzio dal sensore: la lettura HR non è più affidabile
    }

    if (nowMs - lastSpo2SampleMs >= SPO2_SAMPLE_INTERVAL_MS) {  // SpO2 campionata a tempo fisso, non ad evento
      lastSpo2SampleMs = nowMs;
      sampleSpo2();
    }
  }

  if (nowMs - lastFsmUpdateMs >= FSM_UPDATE_INTERVAL_MS) {
    lastFsmUpdateMs = nowMs;
    readingValid = hrReady && spo2Ready;  // valida solo se ENTRAMBE le catene sono agganciate
    if (readingValid) {
      lastValidBpm  = bpm;
      lastValidSpo2 = spo2;
    }
    updateFsm();              // fa avanzare la macchina a stati
    if (SERIAL_PLOTTER) printPlotterTelemetry();  // una riga di valori per il Plotter seriale
  }

  if (nowMs - lastDisplayUpdateMs >= DISPLAY_UPDATE_INTERVAL_MS) {
    lastDisplayUpdateMs = nowMs;
    updateLcd();   // aggiorna il testo sullo schermo
    updateLeds();  // aggiorna i LED
  }

  updateVibration();  // ogni giro: i battiti brevi richiedono tempi precisi

  // --- Canale MQTT ---
  // Quando la connessione manca, il ciclo la ritenta con ensureNetwork() ogni
  // NETWORK_RETRY_INTERVAL_MS. Fra un tentativo e l'altro prosegue con gli
  // altri compiti, pertanto una rete assente non ferma il dispositivo.
  finishBrokerConnect();
  // Mentre il task di collegamento lavora mqtt e' suo: per il loop il broker
  // non e' collegato.
  bool brokerConnected = !brokerConnectRunning && mqtt.connected();
  trackNetwork(brokerConnected);  // avviso sull'LCD se la rete cade (a lungo) o torna
  if (brokerConnected) {
    if (isBrokerWritable()) {
      brokerWritableSinceMs = millis();
      mqtt.loop();  // fa "respirare" la libreria MQTT: elabora messaggi in arrivo, mantiene viva la connessione
      sendPendingBiometricAlarm();
      if (nowMs - lastPublishMs >= PUBLISH_INTERVAL_MS) {
        lastPublishMs = nowMs;
        publishTelemetry();
      }
    } else if (millis() - brokerWritableSinceMs >= BROKER_STALL_MS) {
      // Il broker non svuota piu' il buffer: la connessione e' morta anche se
      // nessuno l'ha chiusa. Chiuderla qui fa ripartire il ricollegamento.
      Serial.println("[RETE] il broker non riceve piu' dati, chiudo la connessione");
      wifiClient.stop();
    }
  } else if (!brokerConnectRunning && nowMs - lastNetworkRetryMs >= NETWORK_RETRY_INTERVAL_MS) {
    lastNetworkRetryMs = nowMs;
    ensureNetwork();
  }

  logStateChange();  // ultimo: raccoglie i cambi di stato fatti in qualunque punto del giro
}

// ================== CONTROLLO SENSORE ==================

// true se il sensore risponde ed e' ancora nella modalita' impostata da
// pox.begin(). Uno staccato e riattaccato fra due controlli risponde, ma si e'
// riacceso con la configurazione azzerata e non misura piu' nulla.
bool isSensorResponding() {
  Wire.beginTransmission(MAX30100_I2C_ADDRESS);
  Wire.write(MAX30100_REG_MODE_CONFIGURATION);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(MAX30100_I2C_ADDRESS, 1) != 1) return false;
  return (Wire.read() & 0x07) == MAX30100_MODE_SPO2_HR;
}

// Interroga il sensore agganciato ogni SENSOR_CHECK_INTERVAL_MS. Dopo
// SENSOR_MAX_MISSED_CHECKS risposte mancate lo da' per perso: azzera le
// letture e lascia a retrySensorIfMissing() il riaggancio.
void checkSensorConnection() {
  if (!sensorPresent) return;

  unsigned long nowMs = millis();
  if (nowMs - lastSensorCheckMs < SENSOR_CHECK_INTERVAL_MS) return;
  lastSensorCheckMs = nowMs;

  if (isSensorResponding()) {
    missedSensorChecks = 0;
    return;
  }
  missedSensorChecks++;
  if (missedSensorChecks < SENSOR_MAX_MISSED_CHECKS) return;

  missedSensorChecks = 0;
  sensorPresent = false;
  resetHr();
  resetSpo2();
  readingValid = false;
  lastSensorRetryMs = nowMs;
  // Senza missione updateFsm() non gira: z6 va impostato qui. In missione ci
  // pensa l'automa, dopo un eventuale allarme in corso.
  if (currentState == STATE_MISSION_NOT_STARTED) currentState = STATE_FAULT;
  Serial.print("[SENSORE] non risponde piu', riprovo ogni ");
  Serial.print(SENSOR_RETRY_INTERVAL_MS / 1000);
  Serial.println(" s");
}

// ================== RITENTATIVO SENSORE IN BACKGROUND ==================

// Se il sensore non è mai stato agganciato (o si è "perso" per un guasto),
// questa funzione riprova periodicamente SENZA bloccare il resto del
// dispositivo (niente delay()): se il contatto fisico si ristabilisce da
// solo, il dispositivo si riprende automaticamente, senza bisogno di un
// riavvio manuale.
void retrySensorIfMissing() {
  if (sensorPresent) return;  // niente da fare se il sensore è già ok

  unsigned long nowMs = millis();
  if (nowMs - lastSensorRetryMs < SENSOR_RETRY_INTERVAL_MS) return;  // non è ancora ora di riprovare
  lastSensorRetryMs = nowMs;

  if (pox.begin()) {
    configureSensor();
    if (currentState == STATE_FAULT) {
      // evento s: torna a cercare il segnale, non direttamente a STATE_NORMAL;
      // fuori missione torna invece in attesa dell'avvio
      currentState = missionActive ? STATE_SEARCHING_SIGNAL : STATE_MISSION_NOT_STARTED;
    }
    Serial.println("[SENSORE] ricollegato");
  } else {
    Serial.print("[SENSORE] ancora assente, riprovo tra ");
    Serial.print(SENSOR_RETRY_INTERVAL_MS / 1000);
    Serial.println(" s");
  }
}

// ================== CATENA HR (a eventi) ==================

// Azzera completamente lo stato della catena di filtraggio del battito:
// richiamata sia dopo un timeout prolungato di silenzio dal sensore, sia
// internamente da sampleHr() quando serve un nuovo aggancio da zero.
void resetHr() {
  hrReady = false;
  hrBufferCount = 0;
  hrBufferIndex = 0;
  hrFiltered = 0;
  bpm = 0;
  consecutiveHrRejections = 0;
}

// Chiamata UNA VOLTA PER OGNI BATTITO REALE rilevato (non a intervalli
// fissi): legge il valore grezzo, lo filtra in due stadi (mediana, poi
// media mobile esponenziale) e aggiorna bpm.
void sampleHr() {
  hrRaw = pox.getHeartRate();

  if (hrRaw < 30 || hrRaw > 220) return;  // gate di plausibilità fisiologica: fuori da qui, scarta subito

  if (hrReady) {
    // Controllo di qualità: un salto troppo grande rispetto al valore già
    // agganciato è quasi certamente un artefatto da movimento, non un vero
    // cambiamento fisiologico (vedi spiegazione dettagliata data a parte).
    float deviation = fabs(hrRaw - hrFiltered) / hrFiltered;
    if (deviation > HR_MAX_DEVIATION_RATIO) {
      consecutiveHrRejections++;
      if (consecutiveHrRejections >= HR_MAX_REJECTIONS) {
        // Troppi scarti di fila: il valore agganciato è probabilmente
        // sbagliato (es. rumore all'inizio) - meglio ripartire da zero
        // piuttosto che restare bloccati per sempre su un valore sbagliato.
        Serial.println("[SENSORE] battito instabile, riaggancio la lettura");
        resetHr();
      } else {
        return;  // battito scartato, ma la catena resta agganciata per ora
      }
    } else {
      consecutiveHrRejections = 0;  // battito accettato: azzera il contatore degli scarti
    }
  }

  // Stadio 1: inserisce il campione nel buffer circolare e calcola la mediana
  hrBuffer[hrBufferIndex] = hrRaw;
  hrBufferIndex = (hrBufferIndex + 1) % HR_MEDIAN_WINDOW;  // torna a 0 dopo l'ultima casella
  if (hrBufferCount < HR_MEDIAN_WINDOW) hrBufferCount++;

  if (hrBufferCount < 3) return;  // servono almeno 3 campioni prima di dare un risultato

  int medianCount = (hrBufferCount % 2 == 0) ? hrBufferCount - 1 : hrBufferCount;  // la mediana vuole un numero dispari di elementi
  // Finche' il buffer non e' pieno i campioni stanno in ordine dall'inizio:
  // si prendono gli ultimi medianCount, i piu' recenti. A buffer pieno
  // medianCount e' l'intera finestra e lo scostamento vale zero.
  float hrMedian = computeMedian(hrBuffer + (hrBufferCount - medianCount), medianCount);

  // Stadio 2: media mobile esponenziale sopra il valore mediano
  if (!hrReady) {
    hrFiltered = hrMedian;  // primo aggancio: nessuno smussamento, si parte diretti dal valore
    hrReady = true;
  } else {
    hrFiltered = HR_EMA_ALPHA * hrMedian + (1.0 - HR_EMA_ALPHA) * hrFiltered;
  }

  bpm = (int)(hrFiltered + 0.5);  // arrotonda al numero intero più vicino
}

// ================== CATENA SpO2 (temporizzata, 1 Hz) ==================

// Analoga a resetHr(), ma per la catena della saturazione di ossigeno.
void resetSpo2() {
  spo2Ready = false;
  spo2BufferCount = 0;
  spo2BufferIndex = 0;
  spo2Filtered = 0;
  spo2 = 0;
  consecutiveSpo2OutOfRange = 0;
}

// A differenza di sampleHr() (guidata da evento), questa viene chiamata
// a intervalli fissi di 1 secondo dal loop(), perché la SpO2 varia molto
// più lentamente del battito.
void sampleSpo2() {
  spo2Raw = pox.getSpO2();

  // Senza battiti la libreria puo' conservare l'ultima SpO2 calcolata: non e'
  // una misura, e la catena riparte quando i battiti tornano.
  if (millis() - lastBeatMs > HR_STALE_TIMEOUT_MS) {
    resetSpo2();
    return;
  }

  if (spo2Raw < 70 || spo2Raw > 100) {
    // Fuori range plausibile: tollera qualche lettura anomala consecutiva
    // (rumore/disturbo momentaneo) prima di considerare il dito rimosso
    // e resettare tutta la catena.
    consecutiveSpo2OutOfRange++;
    if (consecutiveSpo2OutOfRange >= SPO2_MAX_OUT_OF_RANGE) {
      resetSpo2();
    }
    return;
  }
  consecutiveSpo2OutOfRange = 0;  // lettura valida: azzera il contatore delle anomalie

  spo2Buffer[spo2BufferIndex] = spo2Raw;
  spo2BufferIndex = (spo2BufferIndex + 1) % SPO2_MEDIAN_WINDOW;
  if (spo2BufferCount < SPO2_MEDIAN_WINDOW) spo2BufferCount++;

  if (spo2BufferCount < 3) return;

  int medianCount = (spo2BufferCount % 2 == 0) ? spo2BufferCount - 1 : spo2BufferCount;
  float spo2Median = computeMedian(spo2Buffer + (spo2BufferCount - medianCount), medianCount);  // ultimi campioni, come per il battito

  if (!spo2Ready) {
    spo2Filtered = spo2Median;
    spo2Ready = true;
  } else {
    spo2Filtered = SPO2_EMA_ALPHA * spo2Median + (1.0 - SPO2_EMA_ALPHA) * spo2Filtered;
  }

  spo2 = (int)(spo2Filtered + 0.5);  // mai sopra 100: le letture oltre il 100% sono scartate a monte
}

// Calcola la mediana di un array: copia i primi n elementi in un buffer
// temporaneo, li ordina (insertion sort, adatto ad array così piccoli), e
// ritorna l'elemento centrale.
float computeMedian(float* buf, int n) {
  float tmp[8];  // capiente abbastanza per entrambe le finestre usate nel programma (5 elementi ciascuna)
  for (int i = 0; i < n; i++) tmp[i] = buf[i];
  for (int i = 1; i < n; i++) {
    float key = tmp[i];
    int j = i - 1;
    while (j >= 0 && tmp[j] > key) {
      tmp[j + 1] = tmp[j];
      j--;
    }
    tmp[j + 1] = key;
  }
  return tmp[n / 2];  // elemento centrale dell'array ordinato
}

// ================== MACCHINA A STATI ==================

// true se almeno uno dei due parametri è fuori dalle soglie "di ingresso"
// (le meno strette) - fa scattare il passaggio da STATE_NORMAL a STATE_VERIFYING.
bool isOutsideEntryThresholds() {
  return (bpm < BPM_MIN_IN || bpm > BPM_MAX_IN || spo2 < SPO2_MIN_IN);
}

// true solo se ENTRAMBI i parametri sono dentro le soglie "di uscita" (le
// più strette) - usata per uscire dall'allarme biometrico con isteresi vera.
bool isWithinExitThresholds() {
  return (bpm >= BPM_MIN_OUT && bpm <= BPM_MAX_OUT && spo2 >= SPO2_MIN_OUT);
}

// La funzione più importante del programma: fa avanzare l'automa di uno
// "scatto" ogni volta che viene chiamata (ogni 250ms dal loop()),
// valutando tutte le condizioni ed eventualmente cambiando 'currentState'.
void updateFsm() {
  // Senza missione nulla da fare: in z0 finche' non arriva "a" (o il bypass di
  // test), in z6 finche' il sensore non risponde (retrySensorIfMissing)
  if (!missionActive) return;

  // Rientro della causa biometrica (isteresi, soglie di uscita)
  if (biometricCauseActive && isWithinExitThresholds()) {
    biometricCauseActive = false;
  }

  // Sorveglianza biometrica mentre l'automa e' gia' in z4/z5 per un'altra
  // causa: li' non passa piu' da z2/z3, dove il controllo e' scritto, e un
  // battito fuori soglia resterebbe invisibile proprio sotto l'allarme meno
  // grave che lo maschera. Stessa persistenza di z3 (evento s4 anche da
  // z4/z5); i due controlli non si sovrappongono perche' valgono in stati
  // diversi.
  if ((currentState == STATE_ALARM || currentState == STATE_SILENCED)
      && !biometricCauseActive && readingValid && isOutsideEntryThresholds()) {
    if (!maskedCriticalPending) {
      maskedCriticalPending = true;
      maskedCriticalStartMs = millis();
    } else if (millis() - maskedCriticalStartMs >= PERSISTENCE_MS) {
      maskedCriticalPending = false;
      biometricCauseActive = true;
      currentState = STATE_ALARM;  // una causa nuova scavalca il silenziamento
      publishBiometricAlarm();     // azione p verso il CC
    }
  } else {
    maskedCriticalPending = false;
  }

  if (isAnyCauseActive()) {
    // Priorita' massima: almeno una causa attiva -> STATE_ALARM, a meno che
    // l'operatore l'abbia gia' silenziata (STATE_SILENCED resta finche' non
    // scade il timer o le cause non si azzerano tutte).
    if (currentState != STATE_SILENCED) currentState = STATE_ALARM;
  } else {
    // Nessuna causa attiva: usciamo da STATE_ALARM/STATE_SILENCED se necessario e
    // rivalutiamo normalmente lo stato in base al sensore/segnale.
    if (currentState == STATE_ALARM || currentState == STATE_SILENCED) {
      currentState = STATE_NORMAL;
    }
    if (!sensorPresent) {
      currentState = STATE_FAULT;
    } else if (!readingValid) {
      currentState = STATE_SEARCHING_SIGNAL;
    }
  }

  // A questo punto 'currentState' riflette già eventuali cambi "globali" (sopra);
  // lo switch gestisce le transizioni specifiche di ciascuno stato.
  switch (currentState) {

    case STATE_SEARCHING_SIGNAL:
      if (readingValid) currentState = STATE_NORMAL;  // evento s1
      break;

    case STATE_NORMAL:
      if (isOutsideEntryThresholds()) {
        currentState = STATE_VERIFYING;               // evento s3
        verifyStartMs = millis();
      }
      break;

    case STATE_VERIFYING:
      if (!isOutsideEntryThresholds()) {
        currentState = STATE_NORMAL;                  // evento u: rientro veloce
      } else if (millis() - verifyStartMs >= PERSISTENCE_MS) {
        biometricCauseActive = true;
        currentState = STATE_ALARM;                   // evento s4 (+ azione p)
        publishBiometricAlarm();
      }
      break;

    case STATE_ALARM:
      // l'uscita e' gestita a monte, quando isAnyCauseActive() diventa falso
      break;

    case STATE_SILENCED:
      if (millis() - silenceStartMs >= SILENCE_TIMEOUT_MS) {
        currentState = STATE_ALARM;                   // evento t: riattivazione automatica
      }
      break;

    case STATE_FAULT:
      if (sensorPresent) {
        currentState = STATE_SEARCHING_SIGNAL;        // evento s
      }
      break;

    default:
      break;
  }
}

// ================== TELEMETRIA ==================

// Stampa una riga di valori sul monitor seriale, in un formato che lo
// Strumenti->Plotter seriale di Arduino IDE sa disegnare come grafico -
// utilissimo durante i test per vedere l'andamento di HR/SpO2 nel tempo.
// Solo valori numerici: lo stato non si puo' disegnare e lo stampa
// logStateChange() a ogni cambio.
void printPlotterTelemetry() {
  Serial.print("HR_grezzo:");
  Serial.print(hrRaw);
  Serial.print(",HR_filtrato:");
  Serial.print(hrFiltered);
  Serial.print(",SpO2_grezzo:");
  Serial.print(spo2Raw);
  Serial.print(",SpO2_filtrato:");
  Serial.println(spo2Filtered);
}

// Stampa sul monitor seriale ogni cambio di stato dell'automa, da qualunque
// punto arrivi: automa, messaggi del drone, pulsante o sensore.
void logStateChange() {
  if (currentState == loggedState) return;
  Serial.print("[STATO] ");
  Serial.print(loggedStateName);
  Serial.print(" -> ");
  Serial.println(getStateName());
  loggedState = currentState;
  loggedStateName = getStateName();
}

// ================== PULSANTE ==================

// Gestisce il pulsante fisico: debounce, rilevamento pressione breve vs
// lunga, e la sequenza a due pressioni lunghe per il reset. Chiamata ad
// OGNI ciclo del loop() (non a intervalli), per non perdere reattività.
void handleButton() {
  bool level = digitalRead(PIN_BUTTON);  // LOW = premuto (per via del pull-up)

  // Debounce a fronte: un cambiamento di livello è considerato "vero" solo
  // se resta stabile per almeno DEBOUNCE_MS, altrimenti è probabilmente un
  // rimbalzo meccanico del contatto.
  if (level != lastRawButtonLevel) {
    lastRawButtonLevel = level;
    lastLevelChangeMs = millis();
  }

  if (millis() - lastLevelChangeMs >= DEBOUNCE_MS) {
    bool pressedNow = (level == LOW);

    if (pressedNow && !buttonPressed) {  // fronte di discesa: inizio di una nuova pressione
      buttonPressed = true;
      pressStartMs = millis();
      longPressCounted = false;
    }
    else if (!pressedNow && buttonPressed) {  // fronte di salita: rilascio
      buttonPressed = false;

      if (longPressCounted) {
        // era una pressione lunga, già gestita al momento giusto più sotto:
        // qui serve solo registrare quando è stata rilasciata, per far
        // partire la finestra di attesa della seconda.
        lastLongPressEndMs = millis();
      } else {
        // pressione breve: silenzia l'allarme, se in corso; fuori missione
        // accende o spegne la prova del sensore biometrico
        pendingResetPresses = 0;
        if (currentState == STATE_ALARM) {
          currentState = STATE_SILENCED;             // evento m
          silenceStartMs = millis();
          Serial.print("[PULSANTE] pressione breve: allarme silenziato per ");
          Serial.print(SILENCE_TIMEOUT_MS / 1000);
          Serial.println(" s");
          updateLeds();  // aggiorna subito l'uscita, senza aspettare il prossimo ciclo di updateLeds() periodico
          updateLcd();
        } else if (!missionActive) {
          toggleSensorTest();
        } else {
          Serial.println("[PULSANTE] pressione breve: nessun allarme da silenziare");
        }
      }
    }
  }

  // Rileva la pressione lunga MENTRE il dito è ancora sul pulsante (non al
  // rilascio), per dare un riscontro immediato all'operatore.
  if (buttonPressed && !longPressCounted &&
      (millis() - pressStartMs >= LONG_PRESS_MS)) {
    longPressCounted = true;

    if (pendingResetPresses == 0) {
      pendingResetPresses = 1;
      Serial.print("[PULSANTE] pressione lunga 1 di 2: ripeti entro ");
      Serial.print(RESET_SEQUENCE_WINDOW_MS / 1000);
      Serial.println(" s per riavviare");
      pulseVibration(150);  // piccolo riscontro tattile: prima lunga accettata
    } else {
      Serial.println("[PULSANTE] pressione lunga 2 di 2: riavvio del dispositivo");
      restartDevice();      // evento r
    }
  }

  // Se la seconda pressione lunga non arriva entro la finestra prevista,
  // la sequenza decade e bisogna ricominciare da capo.
  if (pendingResetPresses == 1 && !buttonPressed &&
      (millis() - lastLongPressEndMs > RESET_SEQUENCE_WINDOW_MS)) {
    pendingResetPresses = 0;
    Serial.println("[PULSANTE] riavvio annullato: la seconda pressione lunga non e' arrivata");
  }
}

// Accende o spegne la prova del sensore biometrico fuori missione (z0), su
// pressione breve del pulsante. Il sensore viene letto e filtrato dal loop()
// in qualunque stato, quindi qui non c'e' nulla da avviare: cambia solo cosa
// mostra l'LCD (updateLcd) e il riscontro dei LED (updateLeds). L'automa
// resta in z0, percio' le soglie non vengono valutate e nessun allarme
// biometrico parte verso il CC: la prova serve a vedere i valori, non a
// sorvegliare l'operatore.
void toggleSensorTest() {
  if (!sensorTestActive && !sensorPresent) {
    // Non c'e' nulla da provare, e l'LCD lo sta gia' dicendo (z6)
    Serial.println("[PULSANTE] pressione breve: prova sensore non disponibile, sensore assente");
    return;
  }

  sensorTestActive = !sensorTestActive;
  Serial.print("[PULSANTE] pressione breve: prova sensore ");
  Serial.println(sensorTestActive ? "attivata" : "disattivata");
  // showNotice aggiorna subito LCD e LED, senza attendere il giro periodico
  if (sensorTestActive) {
    showNotice("Sensore biometr.", "attivo");
  } else {
    showNotice("Prova sensore", "terminata");
  }
}

// Fa vibrare il motore per un tempo breve e fisso: usata come riscontro
// tattile (es. prima pressione lunga accettata) e nella sequenza di reset.
// È bloccante (usa delay()): durante la sua esecuzione il loop() è fermo,
// accettabile solo perché le durate in gioco sono brevi (150-400ms).
void pulseVibration(int durationMs) {
  digitalWrite(PIN_VIBRATION, HIGH);
  delay(durationMs);
  digitalWrite(PIN_VIBRATION, LOW);
}

// Evento r: riavvio software. La missione (se attiva) e' gia' stata
// salvata in Preferences ad ogni AVVIO_MISSIONE/FINE_MISSIONE, quindi al
// prossimo boot il dispositivo la ritrova automaticamente (vedi setup()).
void restartDevice() {
  Serial.flush();  // svuota il buffer seriale prima di riavviare, per non perdere l'ultimo messaggio

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Reset in corso");
  digitalWrite(PIN_LED_RED, HIGH);
  digitalWrite(PIN_LED_GREEN, LOW);
  digitalWrite(PIN_LED_BLUE, LOW);
  pulseVibration(400);

  ESP.restart();  // riavvio vero e proprio del chip: da qui setup() ripartirà da capo
}

// ================== I/O ==================

// Mostra un avviso temporaneo: testo su entrambe le righe dell'LCD e LED blu
// fisso per NOTICE_MS. LCD e LED si aggiornano subito, senza attendere il
// prossimo giro periodico.
void showNotice(const char* line1, const char* line2) {
  noticeLine1 = line1;
  noticeLine2 = line2;
  noticeStartMs = millis();
  Serial.print("[AVVISO] ");
  Serial.print(line1);
  Serial.print(" ");
  Serial.println(line2);
  updateLcd();
  updateLeds();
}

// true mentre l'avviso temporaneo deve restare visibile. Un allarme ha la
// precedenza: il pericolo non aspetta che l'avviso finisca.
bool isNoticeShown() {
  return noticeLine1 != nullptr
      && currentState != STATE_ALARM && currentState != STATE_SILENCED
      && millis() - noticeStartMs < NOTICE_MS;
}

// true mentre l'LCD deve restare fisso su "Connessione persa", in qualunque
// stato: da quando la caduta viene data per certa finche' il broker non torna.
// Prima del primo collegamento non c'e' nulla di perso, e la schermata di z0
// dice a che punto e' il collegamento.
bool isNetworkLossShown() {
  return brokerEverConnected && networkReportedDown;
}

// Segue il collegamento al broker: senza rete l'orologio non riceve gli
// allarmi del drone e non invia la telemetria. La caduta conta solo dopo
// NETWORK_LOSS_GRACE_MS, poi resta segnalata sull'LCD (isNetworkLossShown)
// finche' il collegamento non torna.
void trackNetwork(bool brokerConnected) {
  if (brokerConnected) {
    brokerWasConnected = true;
    brokerEverConnected = true;
    networkReportedDown = false;
    return;
  }
  if (brokerWasConnected) {  // collegamento appena caduto
    brokerWasConnected = false;
    brokerLostSinceMs = millis();
  }
  if (!networkReportedDown && millis() - brokerLostSinceMs >= NETWORK_LOSS_GRACE_MS) {
    networkReportedDown = true;
    Serial.print("[RETE] connessione persa da ");
    Serial.print(NETWORK_LOSS_GRACE_MS / 1000);
    Serial.println(" s");
  }
}

// Stato del WiFi e del broker a parole: seconda riga dell'LCD sotto
// "Connessione", e stesso testo sul monitor seriale. Si chiamano solo a
// collegamento assente. La corrispondenza con i codici numerici e' in
// communication_setup.md.
const char* describeWifiStatus() {
  wl_status_t wifi = WiFi.status();
  if (wifi == WL_NO_SSID_AVAIL)  return "assente";          // router spento o WIFI_SSID errato
  if (wifi == WL_CONNECT_FAILED) return "Password errata";  // WIFI_PASS diversa da quella del router
  return "in corso...";
}

const char* describeBrokerStatus() {
  int broker = mqtt.state();
  if (broker == MQTT_CONNECT_FAILED || broker == MQTT_CONNECTION_TIMEOUT) {
    return "Broker assente";   // Mosquitto spento, IP sbagliato o firewall
  }
  return "al Broker...";
}

// Seconda riga in attesa della missione: dice a che punto e' il collegamento,
// cosi' si controlla anche con l'orologio a batteria, senza monitor seriale.
// Dopo il primo collegamento una caduta la segnala "Connessione persa"
// (isNetworkLossShown), quindi i codici qui servono all'accensione.
const char* buildNetworkStatusText() {
  // Una caduta breve non cambia la scritta (trackNetwork).
  if (!networkReportedDown) return "stabilita";
  if (WiFi.status() != WL_CONNECTED) return describeWifiStatus();
  return describeBrokerStatus();
}

// Aggiorna il testo mostrato sull'LCD in base allo stato corrente e alle
// eventuali cause di allarme attive. Chiamata ogni 250ms dal loop().
// Ogni schermata riempie entrambe le righe, cosi' non restano mai insieme
// meta' di un testo e meta' di un altro; solo il riscontro del pulsante
// prende il posto della seconda riga.
void updateLcd() {
  // Con piu' cause attive insieme si mostra una causa alla volta, a turno:
  // entrambe le righe si riferiscono sempre alla stessa, quindi la causa si
  // sceglie una volta sola qui.
  int cause = selectCauseToDisplay();
  if (cause != displayedCause) {
    displayedCause = cause;
    displayedCauseSinceMs = millis();
  }

  // Priorita': allarme, avviso temporaneo, connessione persa, stato.
  // Con il sensore guasto e la rete persa insieme le due schermate si
  // alternano, come le cause di allarme: nessuna delle due nasconde l'altra.
  bool faultTurn = currentState == STATE_FAULT && (millis() / CAUSE_ROTATION_MS) % 2 == 1;
  String line1, line2;
  if (currentState == STATE_ALARM) {
    buildAlarmLines(cause, line1, line2);
  } else if (currentState == STATE_SILENCED) {
    buildAlarmLines(cause, line1, line2);
    // Lo schermo puo' aggiornarsi poco dopo la scadenza, prima che
    // l'automa torni in allarme: senza il confronto la sottrazione fra
    // valori senza segno darebbe un numero enorme.
    unsigned long silencedMs = millis() - silenceStartMs;
    unsigned long remainingSec = silencedMs < SILENCE_TIMEOUT_MS ? (SILENCE_TIMEOUT_MS - silencedMs) / 1000 : 0;
    line2 = String("Silenziato:") + remainingSec + "s";
  } else if (isNoticeShown()) {
    line1 = noticeLine1;
    line2 = noticeLine2;
  } else if (isNetworkLossShown() && !faultTurn && !sensorTestActive) {
    // La prova del sensore e' stata pensata proprio per funzionare senza
    // rete: finche' e' accesa prende il posto di questa schermata.
    line1 = "Connessione";
    line2 = "persa";
  } else {
    switch (currentState) {
      case STATE_MISSION_NOT_STARTED:
        if (sensorTestActive) {
          buildSensorTestLines(line1, line2);
        } else {
          line1 = "Connessione";
          line2 = buildNetworkStatusText();
        }
        break;
      case STATE_SEARCHING_SIGNAL:
        line1 = "Appoggia il dito";
        line2 = "sul sensore";
        break;
      case STATE_FAULT:
        line1 = "Sensore biometr.";
        line2 = "irraggiungibile";
        break;
      case STATE_VERIFYING:
        line1 = buildVitalsText();
        line2 = "Controllo valori";
        break;
      default:  // STATE_NORMAL
        line1 = buildVitalsText();
        line2 = "Valori normali";
        break;
    }
  }

  unsigned long heldMs = buttonPressed ? (millis() - pressStartMs) : 0;

  if (buttonPressed && heldMs >= 400 && !longPressCounted) {
    // Countdown alla pressione lunga: rilasciando prima si annulla tutto
    int remainingSec = (LONG_PRESS_MS - heldMs + 999) / 1000;
    line2 = String("Tieni premuto:") + remainingSec + "s";
  } else if (pendingResetPresses == 1) {
    line2 = "Ripeti per reset";
  }

  printLcdLine(0, line1);
  printLcdLine(1, line2);
}

// Scrive una riga intera dell'LCD: taglia a 16 caratteri e riempie di spazi
// il resto, cosi' il testo precedente non rimane mai a meta'.
void printLcdLine(int row, const String& text) {
  String line = text;
  if (line.length() > 16) line = line.substring(0, 16);
  while (line.length() < 16) line += ' ';
  lcd.setCursor(0, row);
  lcd.print(line);
}

// Quanti DPI mancano, contati dall'elenco inviato dal drone ("Elmetto, Gilet").
int countMissingPpe() {
  int count = 1;
  for (unsigned int i = 0; i < missingPpeList.length(); i++) {
    if (missingPpeList[i] == ',') count++;
  }
  return count;
}

// Righe dell'allarme biometrico: dicono QUALE parametro e' fuori soglia,
// sopra, e il suo valore, sotto. Se sono fuori entrambi non c'e' spazio per
// le parole e si mostrano i due valori, uno per riga.
// Usano l'ultima lettura valida: durante l'allarme lo stato del segnale non
// si mostra, e una perdita breve non fa alternare la schermata.
void buildBiometricLines(String& line1, String& line2) {
  int bpm  = lastValidBpm;
  int spo2 = lastValidSpo2;

  bool hrHigh  = bpm > BPM_MAX_IN;
  bool hrLow   = bpm < BPM_MIN_IN;
  bool spo2Low = spo2 < SPO2_MIN_IN;
  if (!hrHigh && !hrLow && !spo2Low) {
    // Zona di isteresi: i valori sono rientrati nelle soglie di ingresso ma
    // non ancora in quelle di uscita; si nomina il parametro che tiene
    // acceso l'allarme.
    hrHigh  = bpm > BPM_MAX_OUT;
    hrLow   = bpm < BPM_MIN_OUT;
    spo2Low = spo2 < SPO2_MIN_OUT;
  }
  bool hrOut = hrHigh || hrLow;

  if (hrOut && !spo2Low) {
    line1 = hrHigh ? "Battito alto:" : "Battito basso:";
    line2 = String(bpm) + " bpm";
  } else if (spo2Low && !hrOut) {
    line1 = "SpO2 bassa:";
    line2 = String(spo2) + " %";
  } else {
    // Fuori entrambi, o appena rientrati nel giro prima che l'allarme cessi
    line1 = String("Battito: ") + bpm + " bpm";
    line2 = String("SpO2: ") + spo2 + " %";
  }
}

// Battito e saturazione su una riga: BPM a sinistra, SpO2 allineata a destra.
// Solo con battito a tre cifre e SpO2 al 100% la riga supera i 16 caratteri:
// printLcdLine taglia allora il simbolo "%".
String buildVitalsText() {
  String spo2Text = String("SpO2:") + spo2 + "%";
  String line = String("BPM:") + bpm + " ";
  while (line.length() + spo2Text.length() < LCD_COLUMNS) line += ' ';
  return line + spo2Text;
}

// Righe della prova del sensore fuori missione: gli stessi testi della
// missione attiva - "Appoggia il dito" di z1 finche' la lettura non si
// aggancia, poi battito e saturazione come in z2. La seconda riga dice "Prova
// sensore" e non "Valori normali": fuori missione le soglie non vengono
// valutate, quindi la schermata non puo' promettere che i valori siano a posto.
void buildSensorTestLines(String& line1, String& line2) {
  if (readingValid) {
    line1 = buildVitalsText();
    line2 = "Prova sensore";
  } else {
    line1 = "Appoggia il dito";
    line2 = "sul sensore";
  }
}

// Ordine di gravita' deciso per il progetto: un parametro vitale fuori soglia
// viene prima di un'area interdetta, che viene prima di un DPI mancante.
int getMostSevereCause() {
  if (biometricCauseActive)      return CAUSE_BIOMETRIC;
  if (restrictedAreaCauseActive) return CAUSE_RESTRICTED_AREA;
  if (ppeCauseActive)            return CAUSE_PPE;
  return CAUSE_NONE;
}

// Quale causa mostrare in questo momento. Con una sola causa attiva e' sempre
// quella; con piu' cause si alternano a turno, in ordine fisso (biometrica,
// area, DPI) cosi' il giro e' prevedibile. Una causa NUOVA scavalca il
// turno in corso: un pericolo appena arrivato non deve aspettare il suo giro.
int selectCauseToDisplay() {
  int activeCauses[3];
  int activeCauseCount = 0;
  if (biometricCauseActive)      activeCauses[activeCauseCount++] = CAUSE_BIOMETRIC;
  if (restrictedAreaCauseActive) activeCauses[activeCauseCount++] = CAUSE_RESTRICTED_AREA;
  if (ppeCauseActive)            activeCauses[activeCauseCount++] = CAUSE_PPE;

  int activeMask = 0;
  for (int i = 0; i < activeCauseCount; i++) activeMask |= (1 << activeCauses[i]);
  int newMask = activeMask & ~prevCauseMask;
  prevCauseMask = activeMask;

  if (activeCauseCount == 0) return CAUSE_NONE;
  if (newMask) {
    for (int i = 0; i < activeCauseCount; i++) {
      if (newMask & (1 << activeCauses[i])) return activeCauses[i];
    }
  }
  if (activeCauseCount == 1) return activeCauses[0];

  int displayedIndex = 0;
  bool displayedStillActive = false;
  for (int i = 0; i < activeCauseCount; i++) {
    if (activeCauses[i] == displayedCause) {
      displayedIndex = i;
      displayedStillActive = true;
    }
  }
  if (!displayedStillActive) return activeCauses[0];   // la causa a schermo e' rientrata
  if (millis() - displayedCauseSinceMs < CAUSE_ROTATION_MS) return displayedCause;
  return activeCauses[(displayedIndex + 1) % activeCauseCount];
}

// Testo piu' lungo del display: resta fermo il tempo di leggerne l'inizio,
// poi scorre di un carattere alla volta e ricomincia da capo, con tre spazi a
// fare da stacco tra la fine e l'inizio del giro.
String getScrollWindow(const String& text) {
  if (text.length() <= LCD_COLUMNS) return text;
  unsigned long elapsedMs = millis() - displayedCauseSinceMs;
  if (elapsedMs < SCROLL_START_PAUSE_MS) return text.substring(0, LCD_COLUMNS);

  String ring = text + "   ";
  unsigned int offset = ((elapsedMs - SCROLL_START_PAUSE_MS) / SCROLL_STEP_MS) % ring.length();
  String window = ring.substring(offset);
  while (window.length() < LCD_COLUMNS) window += ring;  // ricuce il giro
  return window.substring(0, LCD_COLUMNS);
}

// Righe dell'allarme per la causa a schermo: il pericolo sopra, sotto cosa
// fare o il dettaglio. Per i DPI la seconda riga e' l'elenco di cosa manca,
// che scorre se non ci sta.
void buildAlarmLines(int cause, String& line1, String& line2) {
  if (cause == CAUSE_BIOMETRIC) {
    buildBiometricLines(line1, line2);
  } else if (cause == CAUSE_RESTRICTED_AREA) {
    line1 = "Area vietata !!";
    line2 = "Allontanarsi";
  } else if (cause == CAUSE_PPE) {
    int count = countMissingPpe();
    if (count > 1) {
      line1 = String(count) + " DPI assenti";
    } else {
      line1 = "DPI assente !!";
    }
    line2 = getScrollWindow(missingPpeList);
  }
}

// Accende o spegne il motore secondo il ritmo della causa a schermo. Viene
// chiamata a ogni giro del loop, non ogni 250 ms come l'LCD: i battiti brevi
// hanno bisogno di una tempistica piu' fine di cosi'.
void updateVibration() {
  int cause = (currentState == STATE_ALARM) ? getMostSevereCause() : CAUSE_NONE;
  if (cause != vibrationCause) {   // cambio di pericolo: il ritmo riparte da un colpo
    vibrationCause = cause;
    vibrationCauseSinceMs = millis();
  }

  bool motorOn = false;
  unsigned long elapsedMs = millis() - vibrationCauseSinceMs;
  if (cause == CAUSE_RESTRICTED_AREA) {
    motorOn = (elapsedMs % AREA_VIBRATION_PERIOD_MS) < AREA_VIBRATION_ON_MS;
  } else if (cause == CAUSE_PPE) {
    motorOn = (elapsedMs % PPE_VIBRATION_PERIOD_MS) < PPE_VIBRATION_ON_MS;
  } else if (cause == CAUSE_BIOMETRIC) {
    motorOn = true;  // allarme biometrico: vibrazione continua
  }
  digitalWrite(PIN_VIBRATION, motorOn ? HIGH : LOW);
}

// Aggiorna i LED in base allo stato corrente - la "traduzione" fisica
// dell'automa in segnali che l'operatore può vedere.
// Chiamata ogni 250ms dal loop(), insieme a updateLcd().
void updateLeds() {
  if (isNoticeShown()) {  // avviso temporaneo: blu fisso
    digitalWrite(PIN_LED_RED, LOW);
    digitalWrite(PIN_LED_GREEN, LOW);
    digitalWrite(PIN_LED_BLUE, HIGH);
    return;
  }

  switch (currentState) {
    case STATE_MISSION_NOT_STARTED:
      digitalWrite(PIN_LED_RED, LOW);
      digitalWrite(PIN_LED_BLUE, LOW);
      if (sensorTestActive) {
        // Durante la prova il LED da' lo stesso riscontro della missione:
        // lampeggio veloce mentre cerca il segnale (come z1), verde fisso a
        // lettura agganciata (come z2).
        digitalWrite(PIN_LED_GREEN, readingValid ? HIGH : (millis() / 500) % 2);
      } else {
        digitalWrite(PIN_LED_GREEN, (millis() / 1000) % 2); // lampeggio lento, 1s
      }
      return;   // nessun'altra elaborazione necessaria prima dell'avvio missione

    case STATE_SEARCHING_SIGNAL:
      digitalWrite(PIN_LED_RED, LOW);
      digitalWrite(PIN_LED_BLUE, LOW);
      digitalWrite(PIN_LED_GREEN, (millis() / 500) % 2);    // lampeggio veloce, 0.5s
      break;

    case STATE_ALARM:
      digitalWrite(PIN_LED_RED, HIGH);
      digitalWrite(PIN_LED_GREEN, LOW);
      digitalWrite(PIN_LED_BLUE, LOW);
      break;

    case STATE_SILENCED:
      digitalWrite(PIN_LED_RED, LOW);
      digitalWrite(PIN_LED_GREEN, LOW);
      digitalWrite(PIN_LED_BLUE, HIGH);
      break;

    case STATE_FAULT:
      digitalWrite(PIN_LED_RED, HIGH);
      digitalWrite(PIN_LED_GREEN, LOW);
      digitalWrite(PIN_LED_BLUE, LOW);
      break;

    default:  // STATE_NORMAL e STATE_VERIFYING: stesso feedback (verde fisso)
      digitalWrite(PIN_LED_RED, LOW);
      digitalWrite(PIN_LED_GREEN, HIGH);
      digitalWrite(PIN_LED_BLUE, LOW);
      break;
  }
}
