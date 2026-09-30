// Parametri di rete di smartwatch.ino. I valori devono coincidere con la
// configurazione del router e del PC descritta in
// communication/communication_setup.md.

#pragma once

// Nome e password della rete Wi-Fi del router 3Com OfficeConnect.
const char* const WIFI_SSID = "WorkGuardian";
const char* const WIFI_PASS = "WorkGuardian2026";

// Indirizzo della scheda Ethernet del PC che esegue il broker Mosquitto.
// Il router lo assegna sempre allo stesso PC, registrato nella sua tabella
// DHCP; un cambio di computer richiede di aggiornare quella registrazione.
const char* const MQTT_BROKER_IP = "192.168.1.2";
