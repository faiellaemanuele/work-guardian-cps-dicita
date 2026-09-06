// ====== Orologio dell'operatore - Nano ESP32 + MAX30100 ======
// LCD 16x2:   RS=D7, EN=D8, D4..D7 = A0..A3 (RW a GND)
// MAX30100:   VIN=3V3, GND, SDA=A4, SCL=A5
// Attuatori:  vibrazione D2, pulsante D3 (verso GND), LED blu D4, verde D5, rosso D6
//
// CAMPIONAMENTO GUIDATO DAGLI EVENTI:
//   Il BPM si campiona A OGNI BATTITO RILEVATO, non a intervalli fissi. La
//   libreria aggiorna getHeartRate() solo quando rileva un battito (~1 Hz):
//   campionare a 4 Hz produceva 3 ripetizioni su 4, cioe' una finestra mediana
//   con meno di 2 battiti distinti e un'EMA che accumulava ritardo su dati privi
//   di informazione nuova. Ora ogni campione e' un battito vero:
//     - la mediana su 5 filtra outlier REALI (un battito perso raddoppia l'RR)
//     - EMA_ALFA_HR puo' stare a 0.35: meno ritardo E piu' stabilita'
//   La SpO2 varia lentamente e resta a campionamento temporizzato (1 Hz).
//
//   Controllo di qualita' senza accelerometro: un battito che si discosta oltre
//   MAX_VARIAZIONE_HR dal valore corrente e' un artefatto da movimento, non
//   fisiologia (il ritmo cardiaco varia in modo graduale) -> scartato.
//
// FSM: STANDBY -> NORMALE -> VERIFICA -> ALLARME -> SILENZIATO, piu' GUASTO
//
// PULSANTE (unico comando, il RESET della scheda non e' accessibile a
// contenitore chiuso):
//   - pressione BREVE          -> silenzia l'allarme
//   - DUE pressioni LUNGHE     -> riavvio del dispositivo
//     La sequenza a due tempi e' immune ai contatti intermittenti: una
//     pressione singola, anche prolungata da un falso contatto, non riavvia.
//
// Telemetria per Serial Plotter (Strumenti -> Plotter seriale, 115200)
// Librerie: MAX30100lib (oxullo), PubSubClient (knolleary)

#include <Wire.h>
#include <LiquidCrystal.h>
#include "MAX30100_PulseOximeter.h"
#include <WiFi.h>
#include <PubSubClient.h>

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

// ---------- Rete e canale MQTT ----------
const char* WIFI_SSID   = "NOME_WIFI";
const char* WIFI_PASS   = "PASSWORD_WIFI";
const char* MQTT_BROKER = "192.168.1.10";
const int   MQTT_PORT   = 1883;
const char* OPERAIO_ID  = "operaio_1";

WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

String topicStato;
String topicPresenza;
const char* TOPIC_ALLARMI = "cantiere/allarmi";

const unsigned long INTERVALLO_PUBBLICA_MS = 500;
const unsigned long RETRY_RETE_MS          = 5000;
unsigned long lastPublishMs   = 0;
unsigned long lastRetryReteMs = 0;
unsigned long notificaCanaleFinoMs = 0;

// ---------- Soglie con ISTERESI ----------
const int BPM_MIN_IN  = 50;
const int BPM_MAX_IN  = 120;
const int SPO2_MIN_IN = 92;
const int BPM_MIN_OUT  = 55;
const int BPM_MAX_OUT  = 115;
const int SPO2_MIN_OUT = 94;

// ---------- Temporizzazioni della FSM ----------
const unsigned long PERSISTENZA_MS   = 3000;
const unsigned long SILENZIO_MAX_MS  = 30000;
const unsigned long HR_TIMEOUT_MS    = 5000;    // Nessun battito -> HR non valido
const unsigned long WATCHDOG_BEAT_MS = 10000;   // Dito presente ma zero battiti -> GUASTO

// ---------- Macchina a stati ----------
enum StatoAllarme { STANDBY, NORMALE, VERIFICA, ALLARME, SILENZIATO, GUASTO };
StatoAllarme stato = STANDBY;
unsigned long inizioVerifica  = 0;
unsigned long inizioSilenzio  = 0;

// ---------- Evento battito ----------
// volatile: il flag e' scritto dal callback della libreria. Il callback viene
// invocato dentro pox.update() (stesso contesto del loop, non e' una ISR), ma
// volatile documenta l'intento e non costa nulla.
volatile bool  nuovoBattito = false;
unsigned long  ultimoBattitoMs = 0;

void onBeatDetected() {
  ultimoBattitoMs = millis();
  nuovoBattito = true;         // C'e' un valore HR nuovo da filtrare
}

// ---------- Parametri di filtraggio ----------
const int   MEDIANA_HR    = 5;      // 5 BATTITI veri (non 5 campioni temporali)
const int   MEDIANA_SPO2  = 5;      // 5 campioni a 1 Hz
const float EMA_ALFA_HR   = 0.35;
const float EMA_ALFA_SPO2 = 0.30;
const float MAX_VARIAZIONE_HR = 0.25;   // 25%: oltre e' artefatto da movimento

float bufHR[MEDIANA_HR];
int   bufHRIndex = 0, bufHRRiempiti = 0;

float bufSpO2[MEDIANA_SPO2];
int   bufSpO2Index = 0, bufSpO2Riempiti = 0;

float hrFiltrato   = 0;
float spo2Filtrato = 0;
bool  hrPronto   = false;      // Catena HR agganciata
bool  spo2Pronto = false;      // Catena SpO2 agganciata

// Ultimi valori grezzi (per il Serial Plotter)
float hrGrezzo   = 0;
float spo2Grezzo = 0;

int bpm  = 0;
int spo2 = 0;
bool letturaValida = false;    // Entrambe le catene pronte

// ---------- Timer ----------
const unsigned long intervalloSpO2    = 1000;   // 1 Hz: la SpO2 varia lentamente
const unsigned long intervalloDisplay = 250;    // 4 Hz
const unsigned long intervalloFSM     = 250;    // 4 Hz
unsigned long lastSpO2    = 0;
unsigned long lastDisplay = 0;
unsigned long lastFSM     = 0;

// ---------- Gestione pulsante: breve = silenzia, due lunghe = reset ----------
const unsigned long DEBOUNCE_MS          = 50;    // Anti-rimbalzo
const unsigned long PRESSIONE_LUNGA_MS   = 2000;  // Soglia "pressione lunga"
const unsigned long FINESTRA_SEQUENZA_MS = 5000;  // Tempo utile per la seconda

bool ultimaLetturaGrezza = HIGH;      // Ultimo livello letto sul pin
bool pulsantePremuto     = false;     // Stato stabile (debounced)
unsigned long ultimoCambioMs    = 0;  // Timestamp ultimo cambio grezzo
unsigned long inizioPressioneMs = 0;  // Inizio della pressione corrente
bool lungaGiaContata = false;         // Questa pressione e' gia' stata contata
int  lunghePerReset  = 0;             // 0 = nessuna, 1 = prima lunga in attesa
unsigned long fineUltimaLungaMs = 0;  // Rilascio della prima lunga

// ================== CANALE MQTT ==================

const char* nomeStato(StatoAllarme s) {
  switch (s) {
    case ALLARME:    return "ALLARME";
    case SILENZIATO: return "SILENZIATO";
    case VERIFICA:   return "VERIFICA";
    case GUASTO:     return "GUASTO";
    case STANDBY:    return "STANDBY";
    default:         return "NORMALE";
  }
}

void pubblicaStato() {
  char payload[160];
  if (letturaValida) {
    snprintf(payload, sizeof(payload),
             "{\"bpm\":%d,\"spo2\":%d,\"stato\":\"%s\",\"lettura_valida\":true}",
             bpm, spo2, nomeStato(stato));
  } else {
    snprintf(payload, sizeof(payload),
             "{\"bpm\":null,\"spo2\":null,\"stato\":\"%s\",\"lettura_valida\":false}",
             nomeStato(stato));
  }
  mqtt.publish(topicStato.c_str(), payload);
}

bool allarmePerMe(const String& msg) {
  int campo = msg.indexOf("\"target\"");
  if (campo < 0) return true;
  int i = msg.indexOf(':', campo);
  if (i < 0) return true;
  i++;
  while (i < (int)msg.length() && msg[i] == ' ') i++;
  if (msg.startsWith("null", i)) return true;
  if (i < (int)msg.length() && msg[i] == '"') {
    int fine = msg.indexOf('"', i + 1);
    if (fine > i) return msg.substring(i + 1, fine) == OPERAIO_ID;
  }
  return false;
}

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  String msg;
  msg.reserve(length);
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
  if (allarmePerMe(msg)) {
    notificaCanaleFinoMs = millis() + 4000;
    Serial.print("CANALE allarme: ");
    Serial.println(msg);
  }
}

void assicuraRete() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    return;
  }
  if (!mqtt.connected()) {
    String clientId = String("wg-orologio_") + OPERAIO_ID;
    if (mqtt.connect(clientId.c_str(), NULL, NULL,
                     topicPresenza.c_str(), 1, true, "offline")) {
      mqtt.publish(topicPresenza.c_str(), "online", true);
      mqtt.subscribe(TOPIC_ALLARMI, 1);
    }
  }
}

// ================== SETUP ==================

void setup() {
  Serial.begin(115200);

  topicStato    = String("cantiere/sensori/orologio/") + OPERAIO_ID;
  topicPresenza = String("cantiere/sistema/orologio_") + OPERAIO_ID + "/status";
  WiFi.mode(WIFI_STA);
  //WiFi.begin(WIFI_SSID, WIFI_PASS);   // Riattivare quando il broker e' pronto
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);
  mqtt.setSocketTimeout(2);

  pinMode(pinVibrazione, OUTPUT);
  pinMode(pinPulsante, INPUT_PULLUP);
  pinMode(pinLedBlu, OUTPUT);
  pinMode(pinLedVerde, OUTPUT);
  pinMode(pinLedRosso, OUTPUT);

  lcd.begin(16, 2);
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Progetto CPS");
  delay(1500);
  lcd.clear();

  digitalWrite(pinVibrazione, LOW);
  digitalWrite(pinLedBlu, LOW);
  digitalWrite(pinLedVerde, HIGH);
  digitalWrite(pinLedRosso, LOW);

  while (!pox.begin()) {
    lcd.setCursor(0, 0);
    lcd.print("MAX30100 assente");
    lcd.setCursor(0, 1);
    lcd.print("Controlla i cavi");
    Serial.println("pox.begin() fallito, ritento...");
    digitalWrite(pinLedRosso, HIGH);
    digitalWrite(pinLedVerde, LOW);
    delay(2000);
  }
  digitalWrite(pinLedRosso, LOW);
  digitalWrite(pinLedVerde, HIGH);
  lcd.clear();

  pox.setIRLedCurrent(MAX30100_LED_CURR_7_6MA);
  pox.setOnBeatDetectedCallback(onBeatDetected);

  unsigned long ora = millis();
  lastSpO2 = lastDisplay = lastFSM = ora;
  ultimoBattitoMs = ora;
}

// ================== LOOP ==================

void loop() {
  pox.update();          // Sempre per primo e senza blocchi

  gestisciPulsante();

  unsigned long ora = millis();

  // ---- HR: filtraggio guidato dall'evento "battito rilevato" ----
  if (nuovoBattito) {
    nuovoBattito = false;
    campionaHR();
  }

  // ---- HR: timeout. Nessun battito da HR_TIMEOUT_MS -> catena invalidata ----
  if (hrPronto && (ora - ultimoBattitoMs > HR_TIMEOUT_MS)) {
    resetHR();
  }

  // ---- SpO2: campionamento temporizzato a 1 Hz ----
  if (ora - lastSpO2 >= intervalloSpO2) {
    lastSpO2 = ora;
    campionaSpO2();
  }

  // ---- FSM e uscite ----
  if (ora - lastFSM >= intervalloFSM) {
    lastFSM = ora;
    letturaValida = hrPronto && spo2Pronto;
    aggiornaFSM();
    telemetriaPlotter();
  }

  if (ora - lastDisplay >= intervalloDisplay) {
    lastDisplay = ora;
    aggiornaLCD();
    aggiornaOutput();
  }

  // --- Canale MQTT (riattivare quando il broker e' disponibile) ---
  /*
  if (mqtt.connected()) {
    mqtt.loop();
    if (ora - lastPublishMs >= INTERVALLO_PUBBLICA_MS) {
      lastPublishMs = ora;
      pubblicaStato();
    }
  } else if (ora - lastRetryReteMs >= RETRY_RETE_MS) {
    lastRetryReteMs = ora;
    assicuraRete();
  }
  */
}

// ================== CATENA HR (a eventi) ==================

void resetHR() {
  hrPronto = false;
  bufHRRiempiti = 0;
  bufHRIndex = 0;
  hrFiltrato = 0;
  bpm = 0;
}

// Chiamata UNA VOLTA PER BATTITO RILEVATO.
void campionaHR() {
  hrGrezzo = pox.getHeartRate();

  // Gate di plausibilita' fisiologica
  if (hrGrezzo < 30 || hrGrezzo > 220) return;

  // Controllo di qualita': il ritmo cardiaco varia in modo graduale, quindi un
  // salto oltre il 25% rispetto al valore corrente e' un artefatto da movimento
  // (o un battito perso/doppio). Attivo solo a catena agganciata, altrimenti
  // bloccherebbe l'aggancio stesso.
  if (hrPronto) {
    float variazione = fabs(hrGrezzo - hrFiltrato) / hrFiltrato;
    if (variazione > MAX_VARIAZIONE_HR) return;   // Battito scartato
  }

  // Stadio 1: mediano su battiti veri
  bufHR[bufHRIndex] = hrGrezzo;
  bufHRIndex = (bufHRIndex + 1) % MEDIANA_HR;
  if (bufHRRiempiti < MEDIANA_HR) bufHRRiempiti++;

  // Bastano 3 battiti per iniziare (~3 s): la finestra si allarga da sola
  if (bufHRRiempiti < 3) return;

  int nMed = (bufHRRiempiti % 2 == 0) ? bufHRRiempiti - 1 : bufHRRiempiti;
  float hrMediano = mediana(bufHR, nMed);

  // Stadio 2: EMA
  if (!hrPronto) {
    hrFiltrato = hrMediano;      // Primo valore: nessuno smussamento
    hrPronto = true;
  } else {
    hrFiltrato = EMA_ALFA_HR * hrMediano + (1.0 - EMA_ALFA_HR) * hrFiltrato;
  }

  bpm = (int)(hrFiltrato + 0.5);
}

// ================== CATENA SpO2 (temporizzata, 1 Hz) ==================

void resetSpO2() {
  spo2Pronto = false;
  bufSpO2Riempiti = 0;
  bufSpO2Index = 0;
  spo2Filtrato = 0;
  spo2 = 0;
}

void campionaSpO2() {
  spo2Grezzo = pox.getSpO2();

  if (spo2Grezzo < 70 || spo2Grezzo > 100) {
    resetSpO2();                 // Dito assente o segnale non agganciato
    return;
  }

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
  if (spo2 > 100) spo2 = 100;
}

// Mediana per copia e insertion sort: n = elementi validi da considerare.
float mediana(float* buf, int n) {
  float tmp[8];                  // >= di entrambe le finestre usate
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
  return tmp[n / 2];
}

// ================== MACCHINA A STATI ==================

bool condizioneCritica() {
  return (bpm < BPM_MIN_IN || bpm > BPM_MAX_IN || spo2 < SPO2_MIN_IN);
}

bool condizioneRientrata() {
  return (bpm >= BPM_MIN_OUT && bpm <= BPM_MAX_OUT && spo2 >= SPO2_MIN_OUT);
}

// Sensore bloccato: la SpO2 e' plausibile (dito presente, sensore che legge) ma
// non arriva nessun battito da troppo tempo -> il rilevamento e' fermo, non e'
// un caso di "dito assente".
bool sensoreBloccato() {
  return spo2Pronto && (millis() - ultimoBattitoMs > WATCHDOG_BEAT_MS);
}

void aggiornaFSM() {
  if (sensoreBloccato()) {
    stato = GUASTO;
  } else if (!letturaValida && stato != GUASTO) {
    stato = STANDBY;
  }

  switch (stato) {

    case STANDBY:
      if (letturaValida) stato = NORMALE;
      break;

    case NORMALE:
      if (condizioneCritica()) {
        stato = VERIFICA;
        inizioVerifica = millis();
      }
      break;

    case VERIFICA:
      if (!condizioneCritica()) {
        stato = NORMALE;
      } else if (millis() - inizioVerifica >= PERSISTENZA_MS) {
        stato = ALLARME;
      }
      break;

    case ALLARME:
      if (condizioneRientrata()) stato = NORMALE;
      break;

    case SILENZIATO:
      if (condizioneRientrata()) {
        stato = NORMALE;
      } else if (millis() - inizioSilenzio >= SILENZIO_MAX_MS) {
        stato = ALLARME;               // SAFETY: riattivazione automatica
      }
      break;

    case GUASTO:
      if (millis() - ultimoBattitoMs <= WATCHDOG_BEAT_MS) {
        stato = NORMALE;
      }
      break;
  }
}

// ================== TELEMETRIA ==================

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
  Serial.println(nomeStato(stato));
}

// ================== PULSANTE ==================

void gestisciPulsante() {
  bool livello = digitalRead(pinPulsante);   // LOW = premuto (INPUT_PULLUP)

  // Debounce a fronti: un livello vale solo se stabile da DEBOUNCE_MS
  if (livello != ultimaLetturaGrezza) {
    ultimaLetturaGrezza = livello;
    ultimoCambioMs = millis();
  }

  if (millis() - ultimoCambioMs >= DEBOUNCE_MS) {
    bool premutoOra = (livello == LOW);

    if (premutoOra && !pulsantePremuto) {          // Fronte: inizio pressione
      pulsantePremuto = true;
      inizioPressioneMs = millis();
      lungaGiaContata = false;
      Serial.println("PULSANTE: premuto");
    }
    else if (!premutoOra && pulsantePremuto) {     // Fronte: rilascio
      pulsantePremuto = false;
      unsigned long durata = millis() - inizioPressioneMs;
      Serial.print("PULSANTE: rilasciato dopo ");
      Serial.print(durata);
      Serial.println(" ms");

      if (lungaGiaContata) {
        fineUltimaLungaMs = millis();   // La finestra parte dal rilascio
      } else {
        // Pressione breve: silenzia l'allarme e annulla la sequenza in corso
        lunghePerReset = 0;
        if (stato == ALLARME) {
          stato = SILENZIATO;
          inizioSilenzio = millis();
          Serial.println("PULSANTE: allarme SILENZIATO");
          aggiornaOutput();
          aggiornaLCD();
        } else {
          Serial.print("PULSANTE: pressione breve ignorata (stato ");
          Serial.print(nomeStato(stato));
          Serial.println(")");
        }
      }
    }
  }

  // Soglia di pressione lunga raggiunta: si conta subito, senza attendere il
  // rilascio, cosi' il riscontro all'utente e' immediato.
  if (pulsantePremuto && !lungaGiaContata &&
      (millis() - inizioPressioneMs >= PRESSIONE_LUNGA_MS)) {
    lungaGiaContata = true;

    if (lunghePerReset == 0) {
      lunghePerReset = 1;
      Serial.println("PULSANTE: pressione lunga 1 di 2 - ripeti per il reset");
      impulsoVibrazione(150);        // Riscontro tattile: prima lunga accettata
    } else {
      Serial.println("PULSANTE: pressione lunga 2 di 2 - RESET");
      eseguiReset();
    }
  }

  // Scadenza della sequenza: la prima lunga decade se la seconda non arriva
  if (lunghePerReset == 1 && !pulsantePremuto &&
      (millis() - fineUltimaLungaMs > FINESTRA_SEQUENZA_MS)) {
    lunghePerReset = 0;
    Serial.println("PULSANTE: sequenza scaduta, reset annullato");
  }
}

// Impulso di vibrazione breve come riscontro all'utente.
void impulsoVibrazione(int ms) {
  digitalWrite(pinVibrazione, HIGH);
  delay(ms);
  digitalWrite(pinVibrazione, LOW);
}

// Riavvio software: il pulsante RESET della scheda non e' accessibile una volta
// chiuso il contenitore dell'orologio.
void eseguiReset() {
  Serial.println("RESET del dispositivo in corso...");
  Serial.flush();                    // Svuota il buffer prima del riavvio

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("RESET in corso");
  digitalWrite(pinLedRosso, HIGH);
  digitalWrite(pinLedVerde, LOW);
  digitalWrite(pinLedBlu, LOW);
  impulsoVibrazione(400);

  ESP.restart();
}

// ================== I/O ==================

void aggiornaLCD() {
  lcd.setCursor(0, 0);
  if (stato == GUASTO) {
    lcd.print("SENSORE ?!      ");
  } else if (stato == STANDBY) {
    lcd.print("Posiziona dito  ");
  } else {
    lcd.print("BPM:");
    lcd.print(bpm);
    lcd.print("   ");
    lcd.setCursor(9, 0);
    lcd.print("S:");
    lcd.print(spo2);
    lcd.print("% ");
  }

  lcd.setCursor(0, 1);

  unsigned long tenuto = pulsantePremuto ? (millis() - inizioPressioneMs) : 0;

  if (pulsantePremuto && tenuto >= 400 && !lungaGiaContata) {
    // Countdown alla pressione lunga: rilasciando prima si annulla
    int rimasti = (PRESSIONE_LUNGA_MS - tenuto + 999) / 1000;
    lcd.print("Tieni... ");
    lcd.print(rimasti);
    lcd.print("s     ");
  } else if (lunghePerReset == 1) {
    lcd.print("Ripeti x reset ");
  } else {
    switch (stato) {
      case STANDBY:    lcd.print("In attesa...   "); break;
      case ALLARME:    lcd.print("ALLARME ATTIVO "); break;
      case SILENZIATO: {
        int rimasti = (SILENZIO_MAX_MS - (millis() - inizioSilenzio)) / 1000;
        if (rimasti < 0) rimasti = 0;
        lcd.print("Silenziato ");
        if (rimasti < 10) lcd.print(" ");
        lcd.print(rimasti);
        lcd.print("s ");
        break;
      }
      case VERIFICA:   lcd.print("Verifica...    "); break;
      case GUASTO:     lcd.print("Controlla sens."); break;
      default:         lcd.print("Valori normali "); break;
    }
  }
}

void aggiornaOutput() {
  switch (stato) {
    case STANDBY:
      digitalWrite(pinVibrazione, LOW);
      digitalWrite(pinLedRosso, LOW);
      digitalWrite(pinLedBlu, LOW);
      digitalWrite(pinLedVerde, (millis() / 500) % 2);   // Lampeggio 1 Hz
      break;

    case ALLARME:
      digitalWrite(pinVibrazione, HIGH);
      digitalWrite(pinLedRosso, HIGH);
      digitalWrite(pinLedVerde, LOW);
      digitalWrite(pinLedBlu, LOW);
      break;

    case SILENZIATO:
      digitalWrite(pinVibrazione, LOW);
      digitalWrite(pinLedRosso, LOW);
      digitalWrite(pinLedVerde, LOW);
      digitalWrite(pinLedBlu, HIGH);
      break;

    case GUASTO:
      digitalWrite(pinVibrazione, LOW);
      digitalWrite(pinLedRosso, HIGH);
      digitalWrite(pinLedVerde, LOW);
      digitalWrite(pinLedBlu, LOW);
      break;

    default:  // NORMALE e VERIFICA
      digitalWrite(pinVibrazione, LOW);
      digitalWrite(pinLedRosso, LOW);
      digitalWrite(pinLedVerde, HIGH);
      digitalWrite(pinLedBlu, LOW);
      break;
  }

  if (millis() < notificaCanaleFinoMs) {
    digitalWrite(pinVibrazione, HIGH);
    digitalWrite(pinLedBlu, HIGH);
  }
}
