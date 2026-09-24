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
//   z0 MISSIONE_NON_AVVIATA - connesso (o in attesa di esserlo) al CC, la
//      missione non e' ancora iniziata. Il ciclo di monitoraggio non e'
//      attivo.
//   z1 RICERCA_SEGNALE - missione attiva, sensore non ancora agganciato.
//   z2 NORMALE - lettura valida, parametri nella norma.
//   z3 VERIFICA - condizione critica rilevata, in attesa di conferma
//      (persistenza).
//   z4 ALLARME - almeno una causa di allarme e' attiva (vedi sotto).
//   z5 SILENZIATO - notifica sospesa dall'operatore, le cause restano
//      tracciate in sottofondo.
//   z6 GUASTO - il sensore non risponde o si e' bloccato.
//
// z0 E IL BYPASS PER I TEST DA BANCO:
//   In funzionamento reale, il dispositivo resta in z0 finche' non riceve
//   dal CC un messaggio {"tipo":"AVVIO_MISSIONE"} (evento "a"). Per i test
//   senza un CC configurato, la costante BYPASS_ATTESA_MISSIONE piu' sotto,
//   se messa a true, salta z0 e fa partire il dispositivo direttamente in
//   z1, come nelle versioni precedenti. IMPORTANTE PER I TEST: ricordarsi
//   di rimetterla a false prima del funzionamento reale sul campo.
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
// ALLARME (z4) A PIU' CAUSE INDIPENDENTI:
//   z4 puo' essere determinato da tre cause indipendenti, tracciate
//   separatamente (causaBiometrica, causaDPI, causaDPC):
//     - causaBiometrica: confermata localmente dopo la persistenza in z3
//       (evento s4), si azzera quando i parametri rientrano secondo le
//       soglie di uscita (evento s5). In questo caso, e SOLO in questo
//       caso, l'orologio informa il CC (azione p).
//     - causaDPI / causaDPC: impostate a true alla ricezione di un
//       messaggio {"tipo":"DPI_MANCANTE"} / {"tipo":"DPC_MANCANTE"} dal
//       CC (evento w1 / w2), azzerate alla ricezione del corrispondente
//       messaggio di risoluzione ({"tipo":"DPI_OK"} / {"tipo":"DPC_OK"},
//       o "RISOLTO" per entrambe).
//   Lo stato resta ALLARME finche' ALMENO UNA causa e' attiva; si esce
//   (evento s5, generalizzato) solo quando NESSUNA causa e' piu' attiva.
//   Se l'operatore silenzia (evento m) mentre piu' cause sono attive, e ne
//   arriva una NUOVA (non un rinnovo di una gia' presente), l'allarme si
//   riattiva subito, scavalcando il silenziamento - nessuna causa nuova
//   resta nascosta. Uscita/ingresso sono valutati ad ogni ciclo, quindi
//   nessuna causa puo' "perdersi". Il canale dal CC porta SOLO messaggi di
//   allarme riconosciuti (DPI/DPC mancante e relative risoluzioni, oltre
//   ad avvio/fine missione): qualunque altro "tipo" ricevuto viene
//   scartato (solo loggato su seriale), non genera alcuna notifica.
//   NOTA: il monitoraggio biometrico resta attivo anche mentre z4/z5 sono
//   gia' in corso per un'altra causa. Il controllo scritto in z2/z3 li' non
//   verrebbe eseguito, quindi un cronometro dedicato (criticoMascherato in
//   aggiornaFSM) ripete la stessa valutazione con la stessa persistenza:
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
//        quelle di attivazione - isteresi vera). Per le cause DPI/DPC,
//        equivale alla ricezione del messaggio di risoluzione dal CC.
//        z4/z5 -> z2 solo quando TUTTE le cause attive sono rientrate.
//
// PULSANTE (unico comando, il RESET della scheda non e' accessibile a
// contenitore chiuso):
//   - pressione BREVE          -> silenzia l'allarme (evento m)
//   - DUE pressioni LUNGHE     -> riavvio del dispositivo (evento r)
//
// NOMENCLATURA EVENTI ALLINEATA AGLI ALTRI AUTOMI DEL SISTEMA (drone/CC):
//   a coincide con "Decollo" del drone. w1/w2 sono la ricezione di allarme
//   DPI/DPC dal CC (generati tipicamente durante una sosta di supervisione
//   del drone, tra i suoi eventi c e d). fm/fa/fc sono i tre distinti modi
//   in cui il drone puo' atterrare (manuale/automatico/critico per
//   batteria): tutti e tre, per l'orologio, valgono come fine missione.
//
// Telemetria per Serial Plotter (Strumenti -> Plotter seriale, 115200)
// Librerie: MAX30100lib (oxullo), PubSubClient (knolleary), Preferences
// (inclusa nel core ESP32 di Arduino)

#include <Wire.h> //il protocollo del sensore
#include <LiquidCrystal.h> //per comunicare con LCD
#include "MAX30100_PulseOximeter.h" //libreria del sensore biometrico
#include <WiFi.h> //libreria per la connessione wi-fi
#include <PubSubClient.h> //libreria per protocollo MQTT
#include <Preferences.h> //Libreria per scrivere o leggere dati nella memoria permanente della scheda (sopravvive ai riavvii)

// ---------- Test da banco senza CC ----------
// true  = salta z0 e parte direttamente in ricerca segnale (comodo per i
//         test in laboratorio, senza dover simulare un "avvio missione")
// false = comportamento reale: resta in z0 finche' non arriva "a" dal CC
const bool BYPASS_ATTESA_MISSIONE = true;

// ---------- LCD ----------
const int rs = 7, en = 8, d4 = A0, d5 = A1, d6 = A2, d7 = A3;
LiquidCrystal lcd(rs, en, d4, d5, d6, d7);

// ---------- Attuatori e pulsante ----------
const int pinVibrazione = 2;
const int pinPulsante   = 3;
const int pinLedBlu     = 4;
const int pinLedVerde   = 5;
const int pinLedRosso   = 6;

// ---------- Sensore ----------
PulseOximeter pox;

const LEDCurrent CORRENTE_LED_IR = MAX30100_LED_CURR_14_2MA;

bool sensorePresente = false; // il sensore risponde correttamente?
const int MAX_TENTATIVI_SENSORE = 10; // quante volte riprovare ad agganciare il sensore all'accensione
const unsigned long RETRY_SENSORE_MS = 30000; // ogni quanto riprovare in sottofondo se manca
unsigned long ultimoRetrySensoreMs = 0; // un "segnaposto" che ricorda quando è stato fatto l'ultimo tentativo.

// ---------- Persistenza missione (sopravvive a un reset) ----------
Preferences prefs; // oggetto che verrà utilizzato per accedere alla memoria permanente
bool missioneAttiva = false; // tiene traccia (in RAM) se la missione è in corso

// ---------- Rete e canale MQTT ----------
// *** DA CONFERMARE: valori placeholder, sostituire con quelli reali ***
const char* WIFI_SSID   = "iPhone di Michele";
const char* WIFI_PASS   = "12345678";
const char* MQTT_BROKER = "172.20.10.2";
const int   MQTT_PORT   = 1883;
const char* OPERAIO_ID  = "operaio_1";   // *** DA CONFERMARE per ogni dispositivo ***

WiFiClient   wifiClient;  // connessione di rete "grezza"
PubSubClient mqtt(wifiClient);  // livello sopra che parla il protocollo MQTT usando quella connessione

String topicStato;         // *** DA CONFERMARE: nome topic definitivo *** (riempito in setup(), dipende da OPERAIO_ID)
String topicPresenza;      // *** DA CONFERMARE: nome topic definitivo ***
const char* TOPIC_ALLARMI = "cantiere/allarmi";   // *** DA CONFERMARE: nome del "canale" su cui l'orologio si mette in ascolto per ricevere messaggi dal CC***

const unsigned long INTERVALLO_PUBBLICA_MS = 500; // Ogni quanto inviare la telemetria
const unsigned long RETRY_RETE_MS          = 5000;// Ogni quanto ritentare la connessione se caduta
unsigned long lastPublishMs   = 0; // due "orologi interni" che ricordano 
unsigned long lastRetryReteMs = 0; // l'ultima volta che ciascuna delle due cose è successa

// ---------- Cause di allarme (z4) ----------
// I tre "interruttori" indipendenti che, combinati, decidono se lo stato
// deve essere ALLARME: basta che uno solo sia vero.
bool causaBiometrica = false;
bool causaDPI = false;
bool causaDPC = false;
bool causaArea = false;  // persona in area vietata, segnalata dal drone
bool causeAttive() { return causaBiometrica || causaDPI || causaDPC || causaArea; } // true se almeno una causa è attiva

// Elenco dei DPI mancanti inviato dal drone (es. "GILET, ELMETTO"): serve
// solo per l'LCD, l'allarme resta una causa sola.
String dettaglioDPI = "";

// ---------- Visualizzazione delle cause sull'LCD ----------
// Identificativi usati solo per decidere cosa scrivere sul display.
const int CAUSA_NESSUNA     = -1;
const int CAUSA_BIOMETRICA  = 0;
const int CAUSA_AREA        = 1;
const int CAUSA_DPI         = 2;
const int CAUSA_DPC         = 3;

const unsigned int  COLONNE_LCD         = 16;
const unsigned long ROTAZIONE_CAUSE_MS  = 4000;  // con piu' allarmi insieme, quanto resta a schermo ciascuno
const unsigned long SCORRIMENTO_MS      = 450;   // ogni quanto scorre di un carattere un testo troppo lungo
const unsigned long PAUSA_SCORRIMENTO_MS = 1500; // quanto resta fermo l'inizio del testo prima di scorrere

// ---------- Ritmi della vibrazione ----------
// Il ritmo segue la causa mostrata sull'LCD, cosi' l'operatore distingue al
// polso di che allarme si tratta senza guardare: continua per il pericolo
// medico, battiti ravvicinati per l'area vietata, un colpo ogni tanto per i
// DPI, che sono un richiamo e non un'emergenza immediata.
const unsigned long VIBRA_AREA_ACCESA_MS = 250;
const unsigned long VIBRA_AREA_CICLO_MS  = 500;
const unsigned long VIBRA_DPI_ACCESA_MS  = 300;
const unsigned long VIBRA_DPI_CICLO_MS   = 1500;

// Da quando e' a schermo la causa attuale: lo scorrimento riparte da capo a
// ogni cambio di causa, altrimenti l'elenco ricomparirebbe a meta' parola.
int causaMostrata = CAUSA_NESSUNA;
unsigned long causaMostrataDa = 0;
int mascheraCausePrec = 0;  // quali cause erano attive al giro precedente

// La vibrazione NON segue il testo a schermo ma la causa piu' grave attiva:
// leggere richiede tempo e le schermate si alternano, mentre il polso deve
// dire sempre qual e' il pericolo peggiore, anche mentre si legge un altro.
int causaVibrazione = CAUSA_NESSUNA;
unsigned long causaVibrazioneDa = 0;

// ---------- Soglie con ISTERESI ----------
// I limiti che, se superati, fanno scattare la condizione critica 

// soglie "di ingresso" nell'allarme
const int BPM_MIN_IN  = 50;
const int BPM_MAX_IN  = 120;
const int SPO2_MIN_IN = 92;
// soglie "di uscita" nell'allarme (più strette: isteresi, evita lo sfarfallio)
const int BPM_MIN_OUT  = 55;
const int BPM_MAX_OUT  = 115;
const int SPO2_MIN_OUT = 94;

// ---------- Temporizzazioni della FSM ----------
const unsigned long PERSISTENZA_MS   = 3000; // quanto deve durare una condizione critica prima di essere confermata (evento s4)
const unsigned long SILENZIO_MAX_MS  = 30000; // quanto dura al massimo un silenziamento prima di riattivarsi da solo (evento t)
const unsigned long HR_TIMEOUT_MS    = 5000; //Se non arriva nessun battito per 5 secondi, la lettura del battito viene considerata non più valida
const unsigned long WATCHDOG_BEAT_MS = 10000; //Se il dito sembra presente (SpO2 plausibile) ma non arriva nessun battito per 10 secondi, è un guasto vero (non solo "dito non messo").

// ---------- Macchina a stati ----------
// Corrispondenza con la nomenclatura dell'automa: z0=MISSIONE_NON_AVVIATA,
// z1=RICERCA_SEGNALE, z2=NORMALE, z3=VERIFICA, z4=ALLARME, z5=SILENZIATO,
// z6=GUASTO
enum StatoAllarme {
  MISSIONE_NON_AVVIATA,
  RICERCA_SEGNALE,
  NORMALE,
  VERIFICA,
  ALLARME,
  SILENZIATO,
  GUASTO
};

StatoAllarme stato = MISSIONE_NON_AVVIATA; // la variabile più importante: dice "dove si trova" il dispositivo nell'automa
// Due "cronometri": memorizzano quando (in millisecondi 
//dall'accensione) si è entrati in VERIFICA o in SILENZIATO, 
//per poter calcolare dopo quanto tempo è trascorso.
unsigned long inizioVerifica  = 0;
unsigned long inizioSilenzio  = 0;

// Persistenza della condizione critica quando l'automa si trova gia' in
// z4/z5 per un'altra causa: li' non passa piu' da z2/z3, dove il controllo
// biometrico e' scritto, e serve un cronometro dedicato.
bool criticoMascherato = false;
unsigned long inizioCriticoMascherato = 0;

// ---------- Evento battito ----------
volatile bool  nuovoBattito = false; // "volatile": puo' cambiare in momenti imprevedibili (scritta dalla callback qui sotto)
unsigned long  ultimoBattitoMs = 0; // memorizza quando è arrivato l'ultimo battito reale

// Questa funzione non la chiamiamo mai noi direttamente nel codice
// — viene chiamata automaticamente dalla libreria del sensore ogni 
// volta che rileva un battito vero
void onBeatDetected() {
  ultimoBattitoMs = millis();
  nuovoBattito = true;
}

// ---------- Parametri di filtraggio ----------
// Quanti campioni tiene in memoria ciascuna delle due 
// "finestre mobili" su cui calcoliamo la mediana
const int   MEDIANA_HR    = 5;
const int   MEDIANA_SPO2  = 5;
// I coefficienti della media mobile esponenziale (EMA): 
//  un numero tra 0 e 1 che decide "quanto peso" dare al nuovo campione
// rispetto alla storia precedente
const float EMA_ALFA_HR   = 0.35;
const float EMA_ALFA_SPO2 = 0.30;
const float MAX_VARIAZIONE_HR = 0.25; // È la soglia massima di variazione percentuale che un nuovo battito può avere rispetto al valore già filtrato, per essere accettato come "vero".

const int MAX_RIFIUTI_HR = 6; //se vengono scartati 6 battiti di fila, la catena si ri-aggancia da zero
int rifiutiConsecutiviHR = 0; // contatore

const int MAX_FUORI_RANGE_SPO2 = 2;//analogo a sopra
int fuoriRangeConsecutiviSpO2 = 0;

float bufHR[MEDIANA_HR];// array — è la finestra mobile che contiene gli ultimi 5 battiti grezzi, su cui calcoliamo la mediana.
int   bufHRIndex = 0, bufHRRiempiti = 0; // ricorda in quale casella dell'array scrivere il prossimo valore - conta quante caselle sono già state riempite almeno una volta

float bufSpO2[MEDIANA_SPO2]; // analogo a sopra
int   bufSpO2Index = 0, bufSpO2Riempiti = 0;

float hrFiltrato   = 0; // I valori finali, dopo entrambi gli stadi 
float spo2Filtrato = 0; // di filtraggio
bool  hrPronto   = false; //diventano true solo quando la rispettiva 
bool  spo2Pronto = false; // catena si è "agganciata" (almeno 3 campioni validi consecutivi accumulati)

// valori grezzi (prima di qualsiasi filtro, tenuti solo per il debug/telemetria)
float hrGrezzo   = 0;
float spo2Grezzo = 0;

int bpm  = 0; //I valori finali arrotondati a numero intero - quelli 
int spo2 = 0; //che effettivamente vengono mostrati sull'LCD e confrontati con le soglie.
bool letturaValida = false; // true solo quando entrambe le catene (hrPronto e spo2Pronto) sono agganciate

// ---------- Timer ----------
// Ogni quanto (in millisecondi) eseguire ciascun compito periodico
const unsigned long intervalloSpO2    = 1000;
const unsigned long intervalloDisplay = 250;
const unsigned long intervalloFSM     = 250;
// Per ciascuno dei tre, memorizza quando è stato eseguito l'ultima volta
unsigned long lastSpO2    = 0;
unsigned long lastDisplay = 0;
unsigned long lastFSM     = 0;

// ---------- Gestione pulsante ----------
const unsigned long DEBOUNCE_MS          = 50; // Tempo minimo che un livello del pulsante deve restare stabile prima di essere considerato "vero"
const unsigned long PRESSIONE_LUNGA_MS   = 2000; // Quanto tenere premuto perché conti come "pressione lunga"
const unsigned long FINESTRA_SEQUENZA_MS = 5000; // Quanto tempo si ha per fare la seconda pressione lunga dopo la prima, prima che la sequenza di reset scada

bool ultimaLetturaGrezza = HIGH; // L'ultimo livello elettrico letto sul pin del pulsante, "grezzo" (non ancora confermato dal debounce). Parte da HIGH perché a riposo, con INPUT_PULLUP, il pin legge alto.
bool pulsantePremuto     = false; // Lo stato "vero" del pulsante, dopo il debounce
unsigned long ultimoCambioMs    = 0; // quando è cambiato l'ultima volta il livello grezzo
unsigned long inizioPressioneMs = 0; // quando è iniziata la pressione corrente
bool lungaGiaContata = false; // evita di contare due volte la stessa pressione lunga
int  lunghePerReset  = 0; // 0 = nessuna pressione lunga in sospeso, 1 = ne è già arrivata una, in attesa della seconda
unsigned long fineUltimaLungaMs = 0; // quando è finita (rilasciata) l'ultima pressione lunga

// ================== CANALE MQTT ==================
// Da qui in poi iniziano le vere FUNZIONI (non solo dichiarazioni di
// variabili): blocchi di codice riutilizzabile che vengono richiamati per
// nome dal resto del programma.

// Traduce lo stato interno (l'enum StatoAllarme) in una stringa leggibile,
// usata sia per i messaggi di log sul monitor seriale sia per i messaggi
// JSON inviati al CC via MQTT.
// Senza parametro (legge direttamente la variabile globale 'stato'): un
// parametro di tipo enum qui mandava in confusione il generatore automatico
// di prototipi di Arduino IDE, che generava un prototipo errato prima
// ancora che l'enum StatoAllarme fosse visibile, causando un errore di
// compilazione. Tutte le chiamate nel resto del file usano comunque sempre
// e solo la variabile globale 'stato', quindi il parametro era superfluo.
const char* nomeStato() {
  switch (stato) {
    case MISSIONE_NON_AVVIATA: return "MISSIONE_NON_AVVIATA";
    case RICERCA_SEGNALE:      return "RICERCA_SEGNALE";
    case VERIFICA:             return "VERIFICA";
    case ALLARME:              return "ALLARME";
    case SILENZIATO:           return "SILENZIATO";
    case GUASTO:               return "GUASTO";
    default:                   return "NORMALE";
  }
}

// Costruisce un messaggio JSON con i valori correnti (bpm, spo2, stato) e
// lo invia al CC sul topic personale di questo operatore. Chiamata
// periodicamente dal loop(), non solo quando c'è un allarme: è la
// "telemetria continua" che permette al CC di sapere come sta l'operatore
// in ogni momento. Se la lettura non è ancora valida, bpm/spo2 vengono
// inviati come "null" invece di 0, per non far credere al CC che i valori
// siano davvero zero.
void pubblicaStato() {
  char payload[160];  // buffer di testo dove costruiamo il JSON prima di inviarlo
  if (letturaValida) {
    snprintf(payload, sizeof(payload),  // compone la stringa in modo sicuro, senza sforare la dimensione del buffer
             "{\"bpm\":%d,\"spo2\":%d,\"stato\":\"%s\",\"lettura_valida\":true}",
             bpm, spo2, nomeStato());
  } else {
    snprintf(payload, sizeof(payload),
             "{\"bpm\":null,\"spo2\":null,\"stato\":\"%s\",\"lettura_valida\":false}",
             nomeStato());
  }
  mqtt.publish(topicStato.c_str(), payload);  // invio effettivo del messaggio sul topic
}

// Evento singolo, inviato una volta all'ingresso in ALLARME per causa
// BIOMETRICA (azione "p"). Le cause DPI/DPC non generano questo evento: il
// CC gia' sa di aver inviato la segnalazione, non serve confermarglielo.
// A differenza di pubblicaStato() (che gira in continuazione), questa
// funzione viene chiamata una volta sola, esattamente nel momento in cui
// scatta l'allarme biometrico - utile al CC per registrare "quando" è
// successo, non solo "come sta ora".
void pubblicaAllarmeBiometrico() {
  char payload[160];
  snprintf(payload, sizeof(payload),
           "{\"bpm\":%d,\"spo2\":%d,\"evento\":\"BIOMETRIA_ANOMALA\"}",
           bpm, spo2);
  mqtt.publish(topicStato.c_str(), payload);
  Serial.println("MQTT: evento BIOMETRIA_ANOMALA pubblicato (p).");
}

// Estrae il valore stringa di un campo JSON semplice, dato il suo nome
// (es. "tipo" o "target"), senza usare una libreria di parsing JSON vera e
// propria - funziona solo per un formato "piatto" come quello usato qui,
// senza virgolette annidate o caratteri di escape particolari nel valore.
String estraiCampo(const String& msg, const char* nomeCampo) {
  String chiave = String("\"") + nomeCampo + "\"";  // es. "\"tipo\""
  int campo = msg.indexOf(chiave);                  // cerca il nome del campo nel messaggio
  if (campo < 0) return "";                         // campo assente: nessun valore da estrarre
  int i = msg.indexOf(':', campo);                  // cerca il ":" subito dopo il nome del campo
  if (i < 0) return "";
  i++;
  while (i < (int)msg.length() && msg[i] == ' ') i++;  // salta eventuali spazi dopo il ":"
  if (i < (int)msg.length() && msg[i] == '"') {        // il valore deve iniziare con una virgoletta
    int fine = msg.indexOf('"', i + 1);                // cerca la virgoletta di chiusura
    if (fine > i) return msg.substring(i + 1, fine);   // ritorna il testo tra le due virgolette
  }
  return "";
}

// Controlla se un messaggio ricevuto è destinato a QUESTO operatore: se il
// messaggio non ha un campo "target", o lo ha ma vale "null", si considera
// un messaggio broadcast (per tutti); altrimenti va confrontato con
// OPERAIO_ID.
bool allarmePerMe(const String& msg) {
  int campo = msg.indexOf("\"target\"");
  if (campo < 0) return true;   // nessun campo "target": broadcast per tutti
  int i = msg.indexOf(':', campo);
  if (i < 0) return true;
  i++;
  while (i < (int)msg.length() && msg[i] == ' ') i++;
  if (msg.startsWith("null", i)) return true;   // target esplicitamente "null": broadcast per tutti
  if (i < (int)msg.length() && msg[i] == '"') {
    int fine = msg.indexOf('"', i + 1);
    if (fine > i) return msg.substring(i + 1, fine) == OPERAIO_ID;  // confronto diretto con il nostro ID
  }
  return false;
}

// Funzione richiamata AUTOMATICAMENTE dalla libreria PubSubClient ogni
// volta che arriva un messaggio su un topic a cui siamo iscritti (vedi
// mqtt.subscribe in assicuraRete() più sotto). È il "centro smistamento"
// di tutto ciò che arriva dal CC: legge il campo "tipo" e decide cosa fare
// in base al suo valore.
void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String msg;
  msg.reserve(length);  // pre-alloca la stringa alla lunghezza giusta, più efficiente
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];  // ricostruisce il testo byte per byte

  if (!allarmePerMe(msg)) return;  // messaggio per un altro operatore: ignoralo del tutto

  String tipo = estraiCampo(msg, "tipo");
  Serial.print("CANALE messaggio ricevuto, tipo='");
  Serial.print(tipo);
  Serial.print("': ");
  Serial.println(msg);

  // ---- Avvio / fine missione (eventi a, fm/fa/fc) ----
  // Nota: a = "Decollo" nell'automa del drone, coincide con l'avvio della
  // missione anche per l'orologio. fm/fa/fc sono i tre modi distinti in
  // cui il drone puo' atterrare (manuale, automatico nominale, critico per
  // batteria) - tutti e tre terminano la missione anche per l'orologio,
  // che pero' non ha bisogno di distinguerli: il CC invia comunque un
  // unico messaggio {"tipo":"FINE_MISSIONE"} indipendentemente da quale
  // dei tre ha innescato l'atterraggio.
  if (tipo == "AVVIO_MISSIONE") {
    missioneAttiva = true;
    prefs.putBool("missione", true);  // salvato in memoria permanente: sopravvive a un reset (r)
    if (stato == MISSIONE_NON_AVVIATA) {
      stato = sensorePresente ? RICERCA_SEGNALE : GUASTO;  // z0 -> z1, oppure z6 se il sensore manca
    }
    return;
  }
  if (tipo == "FINE_MISSIONE") {
    missioneAttiva = false;
    prefs.putBool("missione", false);
    causaBiometrica = false;  // fine missione: azzera tutte le cause di allarme pendenti
    causaDPI = false;
    dettaglioDPI = "";
    causaDPC = false;
    causaArea = false;
    stato = MISSIONE_NON_AVVIATA;  // torna a z0
    return;
  }

  // Se la missione non e' attiva, gli eventi seguenti non sono pertinenti
  // (il CC non dovrebbe inviarli, ma per sicurezza li ignoriamo).
  if (stato == MISSIONE_NON_AVVIATA) return;

  // ---- DPI / DPC (eventi w1, w2, e relative risoluzioni) ----
  if (tipo == "DPI_MANCANTE") {          // evento w1
    bool nuovaCausa = !causaDPI;         // true solo se la causa NON era già attiva (rinnovo vs novità)
    causaDPI = true;
    dettaglioDPI = estraiCampo(msg, "dettaglio");  // quali DPI mancano, per l'LCD
    if (nuovaCausa) stato = ALLARME;   // scavalca anche un SILENZIATO in corso
    return;
  }
  if (tipo == "AREA_VIETATA") {          // persona in area vietata
    bool nuovaCausa = !causaArea;
    causaArea = true;
    if (nuovaCausa) stato = ALLARME;
    return;
  }
  if (tipo == "AREA_OK") { causaArea = false; return; }   // area di nuovo libera
  if (tipo == "DPC_MANCANTE") {          // evento w2
    bool nuovaCausa = !causaDPC;
    causaDPC = true;
    if (nuovaCausa) stato = ALLARME;
    return;
  }
  if (tipo == "DPI_OK") { causaDPI = false; dettaglioDPI = ""; return; }  // risoluzione: contribuisce a s5
  if (tipo == "DPC_OK") { causaDPC = false; return; }
  if (tipo == "RISOLTO") {   // risolve tutte le cause segnalate dal CC in un colpo solo
    causaDPI = false;
    dettaglioDPI = "";
    causaDPC = false;
    causaArea = false;
    return;
  }

  // ---- Qualunque altro "tipo": il canale dal CC porta solo allarmi, un
  // messaggio non riconosciuto viene scartato (solo loggato su seriale) ----
  Serial.println("Tipo di messaggio non riconosciuto, ignorato.");
}

// Gestisce la connessione di rete "a piccoli passi", senza mai bloccare il
// resto del programma: se il WiFi non è connesso, avvia il tentativo (non
// bloccante) e ritorna subito; solo se il WiFi è già su, prova anche MQTT.
// Viene richiamata periodicamente dal loop() quando la connessione manca.
void assicuraRete() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.print("RETE: WiFi non connesso (stato ");
    Serial.print(WiFi.status());
    Serial.print("), provo a collegarmi a ");
    Serial.println(WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    return;
  }
  if (!mqtt.connected()) {
    Serial.print("RETE: WiFi ok, IP orologio ");
    Serial.print(WiFi.localIP());
    Serial.print(" - provo il broker ");
    Serial.print(MQTT_BROKER);
    Serial.print(":");
    Serial.println(MQTT_PORT);
    String clientId = String("wg-orologio_") + OPERAIO_ID;
    // Il quarto/quinto/sesto parametro configurano il "Last Will and
    // Testament": se l'orologio si disconnette in modo anomalo, il broker
    // pubblica automaticamente "offline" sul topic di presenza, così il CC
    // se ne accorge anche senza un messaggio esplicito dell'orologio.
    if (mqtt.connect(clientId.c_str(), NULL, NULL,
                     topicPresenza.c_str(), 1, true, "offline")) {
      mqtt.publish(topicPresenza.c_str(), "online", true);
      mqtt.subscribe(TOPIC_ALLARMI, 1);  // da qui in poi riceveremo i messaggi del CC su questo topic
      Serial.println("RETE: collegato al broker, in ascolto su cantiere/allarmi");
    } else {
      // mqtt.state(): -2 = broker irraggiungibile (IP sbagliato, broker spento
      // o firewall), -4 = nessuna risposta, 5 = accesso non autorizzato
      Serial.print("RETE: broker non raggiungibile, codice ");
      Serial.println(mqtt.state());
    }
  }
}

// ================== SETUP ==================

// Raggruppa la configurazione del sensore, usata sia al primo aggancio in
// setup() sia nei ritentativi in background (ritentaSensoreSeAssente()) -
// evita di duplicare le stesse tre righe in due punti diversi.
void inizializzaSensore() {
  pox.setIRLedCurrent(CORRENTE_LED_IR);
  pox.setOnBeatDetectedCallback(onBeatDetected);  // da qui in poi onBeatDetected() verrà chiamata automaticamente
  sensorePresente = true;
}

// Eseguita UNA SOLA VOLTA all'accensione/reset del dispositivo. Prepara
// tutto ciò che serve prima che il loop() principale inizi a girare.
void setup() {
  Serial.begin(115200);  // apre la porta seriale per log/telemetria verso il PC

  topicStato    = String("cantiere/sensori/orologio/") + OPERAIO_ID;  // costruisce i nomi dei topic ora che OPERAIO_ID è noto
  topicPresenza = String("cantiere/sistema/orologio_") + OPERAIO_ID + "/status";
  WiFi.mode(WIFI_STA);  // modalità "stazione": si collega a una rete esistente, non ne crea una propria
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);  // registra la funzione da chiamare quando arriva un messaggio
  mqtt.setSocketTimeout(2);  // secondi massimi di attesa su operazioni di rete, per non bloccare troppo a lungo

  pinMode(pinVibrazione, OUTPUT);
  pinMode(pinPulsante, INPUT_PULLUP);  // pull-up interno: il pin legge HIGH a riposo, LOW quando premuto
  pinMode(pinLedBlu, OUTPUT);
  pinMode(pinLedVerde, OUTPUT);
  pinMode(pinLedRosso, OUTPUT);

  lcd.begin(16, 2);
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Progetto CPS");  // schermata di benvenuto, solo estetica
  delay(1500);
  lcd.clear();

  // Stato di riposo iniziale degli attuatori, prima ancora di sapere se il
  // sensore risponde: vibrazione spenta, LED verde acceso "di default".
  digitalWrite(pinVibrazione, LOW);
  digitalWrite(pinLedBlu, LOW);
  digitalWrite(pinLedVerde, HIGH);
  digitalWrite(pinLedRosso, LOW);

  // Prova ad agganciare il sensore fino a MAX_TENTATIVI_SENSORE volte,
  // aspettando 2 secondi tra un tentativo e l'altro. A differenza delle
  // versioni molto vecchie del firmware, questo ciclo NON è infinito: se
  // il sensore continua a non rispondere, si esce comunque dopo i
  // tentativi previsti, invece di restare bloccati per sempre.
  int tentativi = 0;
  while (tentativi < MAX_TENTATIVI_SENSORE) {
    if (pox.begin()) {
      inizializzaSensore();
      break;  // aggancio riuscito, esce subito dal ciclo
    }
    tentativi++;
    lcd.setCursor(0, 0);
    lcd.print("MAX30100 assente");
    lcd.setCursor(0, 1);
    lcd.print("Tentativo ");
    lcd.print(tentativi);
    lcd.print("/");
    lcd.print(MAX_TENTATIVI_SENSORE);
    Serial.print("pox.begin() fallito, tentativo ");
    Serial.print(tentativi);
    Serial.println("...");
    digitalWrite(pinLedRosso, HIGH);
    digitalWrite(pinLedVerde, LOW);
    delay(2000);
  }

  lcd.clear();

  // ---- Missione: persistenza attraverso i reset (r) ----
  prefs.begin("orologio", false);  // apre lo spazio di memoria permanente chiamato "orologio"
  missioneAttiva = prefs.getBool("missione", false);  // legge il valore salvato, o false se non esiste ancora

  // Decide lo stato di partenza: se siamo in modalità test (bypass) o se
  // la missione era già attiva prima di un eventuale reset, si salta z0 e
  // si parte direttamente dalla ricerca del segnale (o da GUASTO se il
  // sensore manca); altrimenti si resta in attesa dell'avvio missione.
  if (BYPASS_ATTESA_MISSIONE || missioneAttiva) {
    missioneAttiva = true;
    stato = sensorePresente ? RICERCA_SEGNALE : GUASTO;
  } else {
    stato = MISSIONE_NON_AVVIATA;
  }

  // Aggiorna il feedback visivo iniziale in base all'esito dell'aggancio
  // del sensore, ma solo se la missione è già considerata attiva (altrimenti
  // l'uscita "vera" verrà gestita dal ciclo normale in aggiornaOutput()).
  if (!sensorePresente && stato != MISSIONE_NON_AVVIATA) {
    digitalWrite(pinLedRosso, HIGH);
    digitalWrite(pinLedVerde, LOW);
    lcd.setCursor(0, 0);
    lcd.print("Sensore assente");
    lcd.setCursor(0, 1);
    lcd.print("Modalita' guasto");
    Serial.println("Sensore non trovato dopo il numero massimo di tentativi. Avvio in stato GUASTO.");
  } else if (sensorePresente) {
    digitalWrite(pinLedRosso, LOW);
    digitalWrite(pinLedVerde, HIGH);
  }

  // Inizializza tutti i "cronometri" al tempo corrente, così i primi
  // controlli nel loop() non scattano immediatamente per un falso timeout.
  unsigned long ora = millis();
  lastSpO2 = lastDisplay = lastFSM = ora;
  ultimoBattitoMs = ora;
  ultimoRetrySensoreMs = ora;
}

// ================== LOOP ==================

// Il cuore pulsante del programma: gira all'infinito, migliaia di volte al
// secondo. Ogni "compito" al suo interno è temporizzato in modo indipendente
// (chi ogni ciclo, chi solo ogni tot millisecondi), per tenere il sistema
// reattivo senza sprecare risorse a fare tutto in continuazione.
void loop() {
  if (sensorePresente) {
    pox.update();  // interroga il sensore; se c'è un nuovo battito, scatena onBeatDetected() internamente
  }

  gestisciPulsante();  // controllato ad OGNI ciclo: serve massima reattività per il debounce

  ritentaSensoreSeAssente();  // no-op se il sensore è già presente, altrimenti prova a riagganciarlo ogni tanto

  unsigned long ora = millis();

  if (sensorePresente) {
    if (nuovoBattito) {
      nuovoBattito = false;
      campionaHR();  // elabora il nuovo battito solo quando ce n'è uno vero
    }

    if (hrPronto && (ora - ultimoBattitoMs > HR_TIMEOUT_MS)) {
      resetHR();  // troppo silenzio dal sensore: la lettura HR non è più affidabile
    }

    if (ora - lastSpO2 >= intervalloSpO2) {  // SpO2 campionata a tempo fisso, non ad evento
      lastSpO2 = ora;
      campionaSpO2();
    }
  }

  if (ora - lastFSM >= intervalloFSM) {
    lastFSM = ora;
    letturaValida = hrPronto && spo2Pronto;  // valida solo se ENTRAMBE le catene sono agganciate
    aggiornaFSM();       // fa avanzare la macchina a stati
    telemetriaPlotter();  // stampa una riga di dati sul monitor/plotter seriale
  }

  if (ora - lastDisplay >= intervalloDisplay) {
    lastDisplay = ora;
    aggiornaLCD();     // aggiorna il testo sullo schermo
    aggiornaOutput();  // aggiorna i LED
  }

  aggiornaVibrazione();  // ogni giro: i battiti brevi richiedono tempi precisi

  // --- Canale MQTT ---
  // Con credenziali placeholder, WiFi.begin() non riuscira' mai a connettersi:
  // assicuraRete() lo richiama ogni RETRY_RETE_MS in modo non bloccante, senza
  // effetti collaterali sul resto del dispositivo. Appena i valori reali
  // saranno inseriti, la connessione partira' automaticamente.
  if (mqtt.connected()) {
    mqtt.loop();  // fa "respirare" la libreria MQTT: elabora messaggi in arrivo, mantiene viva la connessione
    if (ora - lastPublishMs >= INTERVALLO_PUBBLICA_MS) {
      lastPublishMs = ora;
      pubblicaStato();
    }
  } else if (ora - lastRetryReteMs >= RETRY_RETE_MS) {
    lastRetryReteMs = ora;
    assicuraRete();
  }
}

// ================== RITENTATIVO SENSORE IN BACKGROUND ==================

// Se il sensore non è mai stato agganciato (o si è "perso" per un guasto),
// questa funzione riprova periodicamente SENZA bloccare il resto del
// dispositivo (niente delay()): se il contatto fisico si ristabilisce da
// solo, il dispositivo si riprende automaticamente, senza bisogno di un
// riavvio manuale.
void ritentaSensoreSeAssente() {
  if (sensorePresente) return;  // niente da fare se il sensore è già ok

  unsigned long ora = millis();
  if (ora - ultimoRetrySensoreMs < RETRY_SENSORE_MS) return;  // non è ancora ora di riprovare
  ultimoRetrySensoreMs = ora;

  Serial.println("Ritento inizializzazione sensore in background...");

  if (pox.begin()) {
    inizializzaSensore();
    if (stato == GUASTO) {
      stato = RICERCA_SEGNALE;  // evento s: torna a cercare il segnale, non direttamente a NORMALE
    }
    Serial.println("Sensore ricollegato con successo!");
  } else {
    Serial.println("Ritentativo fallito, sensore ancora assente.");
  }
}

// ================== CATENA HR (a eventi) ==================

// Azzera completamente lo stato della catena di filtraggio del battito:
// richiamata sia dopo un timeout prolungato di silenzio dal sensore, sia
// internamente da campionaHR() quando serve un nuovo aggancio da zero.
void resetHR() {
  hrPronto = false;
  bufHRRiempiti = 0;
  bufHRIndex = 0;
  hrFiltrato = 0;
  bpm = 0;
  rifiutiConsecutiviHR = 0;
}

// Chiamata UNA VOLTA PER OGNI BATTITO REALE rilevato (non a intervalli
// fissi): legge il valore grezzo, lo filtra in due stadi (mediana, poi
// media mobile esponenziale) e aggiorna bpm.
void campionaHR() {
  hrGrezzo = pox.getHeartRate();

  if (hrGrezzo < 30 || hrGrezzo > 220) return;  // gate di plausibilità fisiologica: fuori da qui, scarta subito

  if (hrPronto) {
    // Controllo di qualità: un salto troppo grande rispetto al valore già
    // agganciato è quasi certamente un artefatto da movimento, non un vero
    // cambiamento fisiologico (vedi spiegazione dettagliata data a parte).
    float variazione = fabs(hrGrezzo - hrFiltrato) / hrFiltrato;
    if (variazione > MAX_VARIAZIONE_HR) {
      rifiutiConsecutiviHR++;
      if (rifiutiConsecutiviHR >= MAX_RIFIUTI_HR) {
        // Troppi scarti di fila: il valore agganciato è probabilmente
        // sbagliato (es. rumore all'inizio) - meglio ripartire da zero
        // piuttosto che restare bloccati per sempre su un valore sbagliato.
        Serial.println("HR: troppi scarti consecutivi, ri-aggancio catena.");
        resetHR();
      } else {
        return;  // battito scartato, ma la catena resta agganciata per ora
      }
    } else {
      rifiutiConsecutiviHR = 0;  // battito accettato: azzera il contatore degli scarti
    }
  }

  // Stadio 1: inserisce il campione nel buffer circolare e calcola la mediana
  bufHR[bufHRIndex] = hrGrezzo;
  bufHRIndex = (bufHRIndex + 1) % MEDIANA_HR;  // torna a 0 dopo l'ultima casella
  if (bufHRRiempiti < MEDIANA_HR) bufHRRiempiti++;

  if (bufHRRiempiti < 3) return;  // servono almeno 3 campioni prima di dare un risultato

  int nMed = (bufHRRiempiti % 2 == 0) ? bufHRRiempiti - 1 : bufHRRiempiti;  // la mediana vuole un numero dispari di elementi
  float hrMediano = mediana(bufHR, nMed);

  // Stadio 2: media mobile esponenziale sopra il valore mediano
  if (!hrPronto) {
    hrFiltrato = hrMediano;  // primo aggancio: nessuno smussamento, si parte diretti dal valore
    hrPronto = true;
  } else {
    hrFiltrato = EMA_ALFA_HR * hrMediano + (1.0 - EMA_ALFA_HR) * hrFiltrato;
  }

  bpm = (int)(hrFiltrato + 0.5);  // arrotonda al numero intero più vicino
}

// ================== CATENA SpO2 (temporizzata, 1 Hz) ==================

// Analoga a resetHR(), ma per la catena della saturazione di ossigeno.
void resetSpO2() {
  spo2Pronto = false;
  bufSpO2Riempiti = 0;
  bufSpO2Index = 0;
  spo2Filtrato = 0;
  spo2 = 0;
  fuoriRangeConsecutiviSpO2 = 0;
}

// A differenza di campionaHR() (guidata da evento), questa viene chiamata
// a intervalli fissi di 1 secondo dal loop(), perché la SpO2 varia molto
// più lentamente del battito.
void campionaSpO2() {
  spo2Grezzo = pox.getSpO2();

  if (spo2Grezzo < 70 || spo2Grezzo > 100) {
    // Fuori range plausibile: tollera qualche lettura anomala consecutiva
    // (rumore/disturbo momentaneo) prima di considerare il dito rimosso
    // e resettare tutta la catena.
    fuoriRangeConsecutiviSpO2++;
    if (fuoriRangeConsecutiviSpO2 >= MAX_FUORI_RANGE_SPO2) {
      resetSpO2();
    }
    return;
  }
  fuoriRangeConsecutiviSpO2 = 0;  // lettura valida: azzera il contatore delle anomalie

  bufSpO2[bufSpO2Index] = spo2Grezzo;
  bufSpO2Index = (bufSpO2Index + 1) % MEDIANA_SPO2;
  if (bufSpO2Riempiti < MEDIANA_SPO2) bufSpO2Riempiti++;

  if (bufSpO2Riempiti < 3) return;

  int nMed = (bufSpO2Riempiti % 2 == 0) ? bufSpO2Riempiti - 1 : bufSpO2Riempiti;
  float spo2Mediano = mediana(bufSpO2, nMed);

  if (!spo2Pronto) {
    spo2Filtrato = spo2Mediano;
    spo2Pronto = true;
  } else {
    spo2Filtrato = EMA_ALFA_SPO2 * spo2Mediano + (1.0 - EMA_ALFA_SPO2) * spo2Filtrato;
  }

  spo2 = (int)(spo2Filtrato + 0.5);
  if (spo2 > 100) spo2 = 100;  // clamp di sicurezza: non può mai superare il 100%
}

// Calcola la mediana di un array: copia i primi n elementi in un buffer
// temporaneo, li ordina (insertion sort, adatto ad array così piccoli), e
// ritorna l'elemento centrale.
float mediana(float* buf, int n) {
  float tmp[8];  // capiente abbastanza per entrambe le finestre usate nel programma (5 elementi ciascuna)
  for (int i = 0; i < n; i++) tmp[i] = buf[i];
  for (int i = 1; i < n; i++) {
    float chiave = tmp[i];
    int j = i - 1;
    while (j >= 0 && tmp[j] > chiave) {
      tmp[j + 1] = tmp[j];
      j--;
    }
    tmp[j + 1] = chiave;
  }
  return tmp[n / 2];  // elemento centrale dell'array ordinato
}

// ================== MACCHINA A STATI ==================

// true se almeno uno dei due parametri è fuori dalle soglie "di ingresso"
// (le meno strette) - fa scattare il passaggio da NORMALE a VERIFICA.
bool condizioneCritica() {
  return (bpm < BPM_MIN_IN || bpm > BPM_MAX_IN || spo2 < SPO2_MIN_IN);
}

// true solo se ENTRAMBI i parametri sono dentro le soglie "di uscita" (le
// più strette) - usata per uscire dall'allarme biometrico con isteresi vera.
bool condizioneRientrata() {
  return (bpm >= BPM_MIN_OUT && bpm <= BPM_MAX_OUT && spo2 >= SPO2_MIN_OUT);
}

// Distingue "dito non presente" da "il sensore ha smesso di funzionare pur
// con un dito plausibile sopra": true solo nel secondo caso, un guasto vero.
bool sensoreBloccato() {
  return sensorePresente && spo2Pronto && (millis() - ultimoBattitoMs > WATCHDOG_BEAT_MS);
}

// La funzione più importante del programma: fa avanzare l'automa di uno
// "scatto" ogni volta che viene chiamata (ogni 250ms dal loop()),
// valutando tutte le condizioni ed eventualmente cambiando 'stato'.
void aggiornaFSM() {
  // z0: nulla da fare finche' non arriva "a" (o il bypass di test)
  if (stato == MISSIONE_NON_AVVIATA) return;

  // Rientro della causa biometrica (isteresi, soglie di uscita)
  if (causaBiometrica && condizioneRientrata()) {
    causaBiometrica = false;
  }

  // Sorveglianza biometrica mentre l'automa e' gia' in z4/z5 per un'altra
  // causa: li' non passa piu' da z2/z3, dove il controllo e' scritto, e un
  // battito fuori soglia resterebbe invisibile proprio sotto l'allarme meno
  // grave che lo maschera. Stessa persistenza di z3 (evento s4 anche da
  // z4/z5); i due controlli non si sovrappongono perche' valgono in stati
  // diversi.
  if ((stato == ALLARME || stato == SILENZIATO)
      && !causaBiometrica && letturaValida && condizioneCritica()) {
    if (!criticoMascherato) {
      criticoMascherato = true;
      inizioCriticoMascherato = millis();
    } else if (millis() - inizioCriticoMascherato >= PERSISTENZA_MS) {
      criticoMascherato = false;
      causaBiometrica = true;
      stato = ALLARME;              // una causa nuova scavalca il silenziamento
      pubblicaAllarmeBiometrico();  // azione p verso il CC
    }
  } else {
    criticoMascherato = false;
  }

  if (causeAttive()) {
    // Priorita' massima: almeno una causa attiva -> ALLARME, a meno che
    // l'operatore l'abbia gia' silenziata (SILENZIATO resta finche' non
    // scade il timer o le cause non si azzerano tutte).
    if (stato != SILENZIATO) stato = ALLARME;
  } else {
    // Nessuna causa attiva: usciamo da ALLARME/SILENZIATO se necessario e
    // rivalutiamo normalmente lo stato in base al sensore/segnale.
    if (stato == ALLARME || stato == SILENZIATO) {
      stato = NORMALE;
    }
    if (!sensorePresente || sensoreBloccato()) {
      stato = GUASTO;
    } else if (!letturaValida) {
      stato = RICERCA_SEGNALE;
    }
  }

  // A questo punto 'stato' riflette già eventuali cambi "globali" (sopra);
  // lo switch gestisce le transizioni specifiche di ciascuno stato.
  switch (stato) {

    case RICERCA_SEGNALE:
      if (letturaValida) stato = NORMALE;   // evento s1
      break;

    case NORMALE:
      if (condizioneCritica()) {
        stato = VERIFICA;                   // evento s3
        inizioVerifica = millis();
      }
      break;

    case VERIFICA:
      if (!condizioneCritica()) {
        stato = NORMALE;                 // evento u: rientro veloce
      } else if (millis() - inizioVerifica >= PERSISTENZA_MS) {
        causaBiometrica = true;
        stato = ALLARME;                 // evento s4 (+ azione p)
        pubblicaAllarmeBiometrico();
      }
      break;

    case ALLARME:
      // l'uscita e' gestita a monte, quando causeAttive() diventa falso
      break;

    case SILENZIATO:
      if (millis() - inizioSilenzio >= SILENZIO_MAX_MS) {
        stato = ALLARME;                 // evento t: riattivazione automatica
      }
      break;

    case GUASTO:
      if (millis() - ultimoBattitoMs <= WATCHDOG_BEAT_MS) {
        stato = RICERCA_SEGNALE;         // evento s (corretto: non piu' NORMALE)
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
void telemetriaPlotter() {
  Serial.print("HR_grezzo:");
  Serial.print(hrGrezzo);
  Serial.print(",HR_filtrato:");
  Serial.print(hrFiltrato);
  Serial.print(",SpO2_grezzo:");
  Serial.print(spo2Grezzo);
  Serial.print(",SpO2_filtrato:");
  Serial.print(spo2Filtrato);
  Serial.print(",STATO:");
  Serial.println(nomeStato());
}

// ================== PULSANTE ==================

// Gestisce il pulsante fisico: debounce, rilevamento pressione breve vs
// lunga, e la sequenza a due pressioni lunghe per il reset. Chiamata ad
// OGNI ciclo del loop() (non a intervalli), per non perdere reattività.
void gestisciPulsante() {
  bool livello = digitalRead(pinPulsante);  // LOW = premuto (per via del pull-up)

  // Debounce a fronte: un cambiamento di livello è considerato "vero" solo
  // se resta stabile per almeno DEBOUNCE_MS, altrimenti è probabilmente un
  // rimbalzo meccanico del contatto.
  if (livello != ultimaLetturaGrezza) {
    ultimaLetturaGrezza = livello;
    ultimoCambioMs = millis();
  }

  if (millis() - ultimoCambioMs >= DEBOUNCE_MS) {
    bool premutoOra = (livello == LOW);

    if (premutoOra && !pulsantePremuto) {  // fronte di discesa: inizio di una nuova pressione
      pulsantePremuto = true;
      inizioPressioneMs = millis();
      lungaGiaContata = false;
      Serial.println("PULSANTE: premuto");
    }
    else if (!premutoOra && pulsantePremuto) {  // fronte di salita: rilascio
      pulsantePremuto = false;
      unsigned long durata = millis() - inizioPressioneMs;
      Serial.print("PULSANTE: rilasciato dopo ");
      Serial.print(durata);
      Serial.println(" ms");

      if (lungaGiaContata) {
        // era una pressione lunga, già gestita al momento giusto più sotto:
        // qui serve solo registrare quando è stata rilasciata, per far
        // partire la finestra di attesa della seconda.
        fineUltimaLungaMs = millis();
      } else {
        // pressione breve: silenzia l'allarme, se in corso
        lunghePerReset = 0;
        if (stato == ALLARME) {
          stato = SILENZIATO;             // evento m
          inizioSilenzio = millis();
          Serial.println("PULSANTE: allarme SILENZIATO");
          aggiornaOutput();  // aggiorna subito l'uscita, senza aspettare il prossimo ciclo di aggiornaOutput() periodico
          aggiornaLCD();
        } else {
          Serial.print("PULSANTE: pressione breve ignorata (stato ");
          Serial.print(nomeStato());
          Serial.println(")");
        }
      }
    }
  }

  // Rileva la pressione lunga MENTRE il dito è ancora sul pulsante (non al
  // rilascio), per dare un riscontro immediato all'operatore.
  if (pulsantePremuto && !lungaGiaContata &&
      (millis() - inizioPressioneMs >= PRESSIONE_LUNGA_MS)) {
    lungaGiaContata = true;

    if (lunghePerReset == 0) {
      lunghePerReset = 1;
      Serial.println("PULSANTE: pressione lunga 1 di 2 - ripeti per il reset");
      impulsoVibrazione(150);  // piccolo riscontro tattile: prima lunga accettata
    } else {
      Serial.println("PULSANTE: pressione lunga 2 di 2 - RESET");
      eseguiReset();           // evento r
    }
  }

  // Se la seconda pressione lunga non arriva entro la finestra prevista,
  // la sequenza decade e bisogna ricominciare da capo.
  if (lunghePerReset == 1 && !pulsantePremuto &&
      (millis() - fineUltimaLungaMs > FINESTRA_SEQUENZA_MS)) {
    lunghePerReset = 0;
    Serial.println("PULSANTE: sequenza scaduta, reset annullato");
  }
}

// Fa vibrare il motore per un tempo breve e fisso: usata come riscontro
// tattile (es. prima pressione lunga accettata) e nella sequenza di reset.
// È bloccante (usa delay()): durante la sua esecuzione il loop() è fermo,
// accettabile solo perché le durate in gioco sono brevi (150-400ms).
void impulsoVibrazione(int ms) {
  digitalWrite(pinVibrazione, HIGH);
  delay(ms);
  digitalWrite(pinVibrazione, LOW);
}

// Evento r: riavvio software. La missione (se attiva) e' gia' stata
// salvata in Preferences ad ogni AVVIO_MISSIONE/FINE_MISSIONE, quindi al
// prossimo boot il dispositivo la ritrova automaticamente (vedi setup()).
void eseguiReset() {
  Serial.println("RESET del dispositivo in corso...");
  Serial.flush();  // svuota il buffer seriale prima di riavviare, per non perdere l'ultimo messaggio

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("RESET in corso");
  digitalWrite(pinLedRosso, HIGH);
  digitalWrite(pinLedVerde, LOW);
  digitalWrite(pinLedBlu, LOW);
  impulsoVibrazione(400);

  ESP.restart();  // riavvio vero e proprio del chip: da qui setup() ripartirà da capo
}

// ================== I/O ==================

// Aggiorna il testo mostrato sull'LCD in base allo stato corrente e alle
// eventuali cause di allarme attive. Chiamata ogni 250ms dal loop().
void aggiornaLCD() {
  // Con piu' cause attive insieme si mostra una causa alla volta, a turno:
  // entrambe le righe si riferiscono sempre alla stessa, quindi la causa si
  // sceglie una volta sola qui.
  int causa = causaDaMostrare();
  if (causa != causaMostrata) {
    causaMostrata = causa;
    causaMostrataDa = millis();
  }

  if (stato == MISSIONE_NON_AVVIATA) {
    stampaRiga(0, "Orologio pronto");
  } else if (stato == ALLARME || stato == SILENZIATO) {
    if (causa == CAUSA_BIOMETRICA) {
      stampaRiga(0, testoBiometrico());
    } else if (causa == CAUSA_AREA) {
      stampaRiga(0, "AREA VIETATA!");
    } else if (causa == CAUSA_DPI) {
      int quanti = quantiDPI();
      if (quanti > 1) {
        stampaRiga(0, String("DPI MANCANTI: ") + quanti);
      } else {
        stampaRiga(0, "DPI MANCANTE!");
      }
    } else if (causa == CAUSA_DPC) {
      stampaRiga(0, "DPC MANCANTE!");
    }
  } else if (stato == GUASTO) {
    stampaRiga(0, "SENSORE GUASTO");
  } else if (stato == RICERCA_SEGNALE) {
    stampaRiga(0, "Posiziona dito");
  } else {
    // NORMALE o VERIFICA: mostra i valori correnti
    stampaRiga(0, String("BPM:") + bpm + "   S:" + spo2 + "%");
  }

  unsigned long tenuto = pulsantePremuto ? (millis() - inizioPressioneMs) : 0;

  if (pulsantePremuto && tenuto >= 400 && !lungaGiaContata) {
    // Countdown alla pressione lunga: rilasciando prima si annulla tutto
    int rimasti = (PRESSIONE_LUNGA_MS - tenuto + 999) / 1000;
    stampaRiga(1, String("Tieni... ") + rimasti + "s");
  } else if (lunghePerReset == 1) {
    stampaRiga(1, "Ripeti x reset");
  } else {
    switch (stato) {
      case MISSIONE_NON_AVVIATA: stampaRiga(1, "Attesa missione"); break;
      case RICERCA_SEGNALE:      stampaRiga(1, "In attesa..."); break;
      case ALLARME:              stampaRiga(1, secondaRigaAllarme(causa)); break;
      case SILENZIATO: {
        int rimasti = (SILENZIO_MAX_MS - (millis() - inizioSilenzio)) / 1000;
        if (rimasti < 0) rimasti = 0;
        stampaRiga(1, String("Silenziato ") + rimasti + "s");
        break;
      }
      case VERIFICA:   stampaRiga(1, "Verifica..."); break;
      case GUASTO:     stampaRiga(1, "Controlla sens."); break;
      default:         stampaRiga(1, "Valori normali"); break;
    }
  }
}

// Scrive una riga intera dell'LCD: taglia a 16 caratteri e riempie di spazi
// il resto, cosi' il testo precedente non rimane mai a meta'.
void stampaRiga(int riga, const String& testo) {
  String t = testo;
  if (t.length() > 16) t = t.substring(0, 16);
  while (t.length() < 16) t += ' ';
  lcd.setCursor(0, riga);
  lcd.print(t);
}

// Quanti DPI mancano, contati dall'elenco inviato dal drone ("GILET, ELMETTO").
int quantiDPI() {
  if (dettaglioDPI.length() == 0) return 1;  // il drone non l'ha mandato: almeno uno manca
  int quanti = 1;
  for (unsigned int i = 0; i < dettaglioDPI.length(); i++) {
    if (dettaglioDPI[i] == ',') quanti++;
  }
  return quanti;
}

// Prima riga durante l'allarme biometrico: dice QUALE parametro e' fuori
// soglia, invece di mostrare due numeri che l'operatore deve interpretare.
// Se sono fuori entrambi non c'e' spazio per le parole e si mostrano i valori.
String testoBiometrico() {
  bool battitoAlto  = bpm > BPM_MAX_IN;
  bool battitoBasso = bpm < BPM_MIN_IN;
  bool spo2Bassa    = spo2 < SPO2_MIN_IN;

  if ((battitoAlto || battitoBasso) && spo2Bassa) {
    return String("BPM:") + bpm + " S:" + spo2 + "%";
  }
  if (battitoAlto)  return String("BATTITO ALTO:") + bpm;
  if (battitoBasso) return String("BATT. BASSO:") + bpm;
  if (spo2Bassa)    return String("SATURAZIONE:") + spo2 + "%";
  return String("BPM:") + bpm + "   S:" + spo2 + "%";
}

// Quanto resta a schermo una causa prima di cedere il turno alla successiva.
// L'elenco dei DPI che non ci sta nel display tiene il turno per un giro
// completo di scorrimento: con 4 s la coda dell'elenco non si leggerebbe mai.
unsigned long durataTurno(int causa) {
  // Il turno lungo vale solo se i DPI sono il pericolo peggiore: con un
  // allarme piu' grave in attesa si torna ai 4 s normali, meglio non leggere
  // tutto l'elenco che far aspettare il pericolo vero.
  if (causa == CAUSA_DPI
      && dettaglioDPI.length() > COLONNE_LCD
      && causaPiuGrave() == CAUSA_DPI) {
    return PAUSA_SCORRIMENTO_MS + (dettaglioDPI.length() + 3) * SCORRIMENTO_MS;
  }
  return ROTAZIONE_CAUSE_MS;
}

// Ordine di gravita' deciso per il progetto: un parametro vitale fuori soglia
// viene prima di un'area interdetta, che viene prima di un DPI mancante.
int causaPiuGrave() {
  if (causaBiometrica) return CAUSA_BIOMETRICA;
  if (causaArea)       return CAUSA_AREA;
  if (causaDPI)        return CAUSA_DPI;
  if (causaDPC)        return CAUSA_DPC;
  return CAUSA_NESSUNA;
}

// Quale causa mostrare in questo momento. Con una sola causa attiva e' sempre
// quella; con piu' cause si alternano a turno, in ordine fisso (biometrica,
// area, DPI, DPC) cosi' il giro e' prevedibile. Una causa NUOVA scavalca il
// turno in corso: un pericolo appena arrivato non deve aspettare il suo giro.
int causaDaMostrare() {
  int attive[4];
  int quante = 0;
  if (causaBiometrica) attive[quante++] = CAUSA_BIOMETRICA;
  if (causaArea)       attive[quante++] = CAUSA_AREA;
  if (causaDPI)        attive[quante++] = CAUSA_DPI;
  if (causaDPC)        attive[quante++] = CAUSA_DPC;

  int maschera = 0;
  for (int i = 0; i < quante; i++) maschera |= (1 << attive[i]);
  int nuove = maschera & ~mascheraCausePrec;
  mascheraCausePrec = maschera;

  if (quante == 0) return CAUSA_NESSUNA;
  if (nuove) {
    for (int i = 0; i < quante; i++) {
      if (nuove & (1 << attive[i])) return attive[i];
    }
  }
  if (quante == 1) return attive[0];

  int indice = 0;
  bool mostrataAncoraAttiva = false;
  for (int i = 0; i < quante; i++) {
    if (attive[i] == causaMostrata) {
      indice = i;
      mostrataAncoraAttiva = true;
    }
  }
  if (!mostrataAncoraAttiva) return attive[0];   // la causa a schermo e' rientrata
  if (millis() - causaMostrataDa < durataTurno(causaMostrata)) return causaMostrata;
  return attive[(indice + 1) % quante];
}

// Testo piu' lungo del display: resta fermo il tempo di leggerne l'inizio,
// poi scorre di un carattere alla volta e ricomincia da capo, con tre spazi a
// fare da stacco tra la fine e l'inizio del giro.
String testoScorrevole(const String& testo) {
  if (testo.length() <= COLONNE_LCD) return testo;
  unsigned long daQuando = millis() - causaMostrataDa;
  if (daQuando < PAUSA_SCORRIMENTO_MS) return testo.substring(0, COLONNE_LCD);

  String anello = testo + "   ";
  unsigned int passo = ((daQuando - PAUSA_SCORRIMENTO_MS) / SCORRIMENTO_MS) % anello.length();
  String finestra = anello.substring(passo);
  while (finestra.length() < COLONNE_LCD) finestra += anello;  // ricuce il giro
  return finestra.substring(0, COLONNE_LCD);
}

// Seconda riga durante l'allarme: per i DPI l'elenco di cosa manca (che
// scorre se non ci sta), per l'area vietata l'istruzione all'operatore,
// altrimenti la scritta generica.
String secondaRigaAllarme(int causa) {
  if (causa == CAUSA_AREA) return "ALLONTANARSI";
  if (causa == CAUSA_DPI && dettaglioDPI.length() > 0) return testoScorrevole(dettaglioDPI);
  return "ALLARME ATTIVO";
}

// Aggiorna LED e vibrazione in base allo stato corrente - la "traduzione"
// fisica dell'automa in segnali che l'operatore può vedere/sentire.
// Chiamata ogni 250ms dal loop(), insieme a aggiornaLCD().
// Accende o spegne il motore secondo il ritmo della causa a schermo. Viene
// chiamata a ogni giro del loop, non ogni 250 ms come l'LCD: i battiti brevi
// hanno bisogno di una tempistica piu' fine di cosi'.
void aggiornaVibrazione() {
  int causa = (stato == ALLARME) ? causaPiuGrave() : CAUSA_NESSUNA;
  if (causa != causaVibrazione) {   // cambio di pericolo: il ritmo riparte da un colpo
    causaVibrazione = causa;
    causaVibrazioneDa = millis();
  }

  bool accesa = false;
  unsigned long daQuando = millis() - causaVibrazioneDa;
  if (causa == CAUSA_AREA) {
    accesa = (daQuando % VIBRA_AREA_CICLO_MS) < VIBRA_AREA_ACCESA_MS;
  } else if (causa == CAUSA_DPI || causa == CAUSA_DPC) {
    accesa = (daQuando % VIBRA_DPI_CICLO_MS) < VIBRA_DPI_ACCESA_MS;
  } else if (causa == CAUSA_BIOMETRICA) {
    accesa = true;  // allarme biometrico: vibrazione continua
  }
  digitalWrite(pinVibrazione, accesa ? HIGH : LOW);
}


void aggiornaOutput() {
  switch (stato) {
    case MISSIONE_NON_AVVIATA:
      digitalWrite(pinLedRosso, LOW);
      digitalWrite(pinLedBlu, LOW);
      digitalWrite(pinLedVerde, (millis() / 1000) % 2);   // lampeggio lento, 1s
      return;   // nessun'altra elaborazione necessaria prima dell'avvio missione

    case RICERCA_SEGNALE:
      digitalWrite(pinLedRosso, LOW);
      digitalWrite(pinLedBlu, LOW);
      digitalWrite(pinLedVerde, (millis() / 500) % 2);    // lampeggio veloce, 0.5s
      break;

    case ALLARME:
      digitalWrite(pinLedRosso, HIGH);
      digitalWrite(pinLedVerde, LOW);
      digitalWrite(pinLedBlu, LOW);
      break;

    case SILENZIATO:
      digitalWrite(pinLedRosso, LOW);
      digitalWrite(pinLedVerde, LOW);
      digitalWrite(pinLedBlu, HIGH);
      break;

    case GUASTO:
      digitalWrite(pinLedRosso, HIGH);
      digitalWrite(pinLedVerde, LOW);
      digitalWrite(pinLedBlu, LOW);
      break;

    default:  // NORMALE e VERIFICA: stesso feedback (verde fisso)
      digitalWrite(pinLedRosso, LOW);
      digitalWrite(pinLedVerde, HIGH);
      digitalWrite(pinLedBlu, LOW);
      break;
  }
}
