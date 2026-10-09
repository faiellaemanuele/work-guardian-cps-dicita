#pragma once

/*
 * Parametri di rete utilizzati da smartwatch.ino.
 *
 * I valori definiti in questo file devono essere coerenti con la configurazione
 * del router e del PC descritta in:
 *
 *   communication/docs/communication_setup.md
 *
 * Separare questi parametri dal firmware consente di aggiornare la rete senza
 * modificare la logica dello smartwatch.
 */

// Credenziali della rete Wi-Fi utilizzata dallo smartwatch.
const char* const WIFI_SSID = "WorkGuardian";
const char* const WIFI_PASS = "WorkGuardian2026";

// Indirizzo Ethernet del PC che esegue il broker MQTT Mosquitto.
// Il router deve riservare questo indirizzo al PC tramite DHCP.
const char* const MQTT_BROKER_IP = "192.168.1.2";
