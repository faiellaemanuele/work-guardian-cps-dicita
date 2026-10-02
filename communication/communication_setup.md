# Avvio della comunicazione

```
Tello  ◄── Wi-Fi ──►  PC (Mosquitto)  ◄── Ethernet ──►  Router  ◄── Wi-Fi ──►  Orologio
```

I comandi vanno eseguiti in una finestra di PowerShell aperta come amministratore.

## 1. Router (solo dopo un reset di fabbrica)

1. Collegare il PC a una porta LAN del router con il cavo Ethernet e aprire nel browser `http://192.168.1.1`. Se compare la procedura guidata Connection Type, ignorarla.
2. In Wireless Settings → Configuration impostare come nome della rete (SSID) `WorkGuardian`, lo stesso valore di `WIFI_SSID` in `wearable/smartwatch/network_config.h`.
3. In Wireless Settings → Encryption scegliere `WPA-PSK (no server)` e inserire come password il valore di `WIFI_PASS`, nello stesso file.

## 2. PC (una volta per ogni computer)

1. Collegare la scheda Ethernet del PC a una porta LAN del router, non alla porta WAN.
2. Assegnare al PC l'indirizzo fisso `192.168.1.2` dalla pagina `http://192.168.1.1` → LAN Settings → tabella DHCP Client Lists:
   - primo PC: spuntare Fix sulla riga con indirizzo `192.168.1.2` e premere Apply;
   - sostituzione del PC, quando la riga `192.168.1.2` è già fissata su un altro computer: premere Edit su quella riga, sostituire il MAC con quello della scheda Ethernet del nuovo PC e premere Apply. Il MAC si legge con `Get-NetAdapter`, colonna `MacAddress`. Poi rinnovare l'indirizzo del nuovo PC:
     ```powershell
     ipconfig /release
     ipconfig /renew
     ```

   In entrambi i casi `ipconfig` deve mostrare `192.168.1.2` sulla scheda Ethernet.
3. Aprire nel firewall di Windows le porte del broker (1883) e del Tello (8890 e 11111):
   ```powershell
   New-NetFirewallRule -DisplayName "WorkGuardian - Mosquitto" -Direction Inbound -Protocol TCP -LocalPort 1883 -RemoteAddress 192.168.1.0/24 -Action Allow
   New-NetFirewallRule -DisplayName "WorkGuardian - Tello" -Direction Inbound -Protocol UDP -LocalPort 8890,11111 -RemoteAddress 192.168.10.1 -Action Allow
   Set-NetFirewallProfile -Profile Public,Private -Enabled True
   ```
4. Installare Mosquitto nella cartella `C:\Program Files\Mosquitto` e impostare ad avvio manuale il servizio creato dall'installazione:
   ```powershell
   Set-Service mosquitto -StartupType Manual
   ```
5. Preparare l'Arduino IDE e caricare il firmware sull'orologio:
   - da Boards Manager installare Arduino ESP32 Boards (di Arduino);
   - da Library Manager installare MAX30100_milan e PubSubClient (di Nick O'Leary);
   - in Tools → Board scegliere Arduino ESP32 Boards → Arduino Nano ESP32;
   - collegare l'orologio via USB, aprire `wearable/smartwatch/smartwatch.ino` e caricarlo.

## 3. Avvio (ogni volta)

1. Accendere il router e verificare con `ipconfig` che la scheda Ethernet del PC abbia `192.168.1.2`.
2. Chiudere le eventuali istanze di Mosquitto già attive. Se non ce ne sono, i due comandi danno errore ed è normale.
   ```powershell
   net stop mosquitto
   taskkill /F /IM mosquitto.exe
   ```
3. Dalla cartella principale del progetto avviare il broker e lasciare la finestra aperta:
   ```powershell
   & "C:\Program Files\Mosquitto\mosquitto.exe" -c "C:\Users\faiel\Desktop\work-guardian-cps\communication\mqtt_broker.conf" -v
   ```
   Deve comparire `Opening ipv4 listen socket on port 1883`. Se Windows chiede l'accesso di rete per Mosquitto, spuntare reti private e pubbliche e premere Consenti accesso.
4. Accendere il Tello, collegare il Wi-Fi del PC alla sua rete (`TELLO-...`) e, in un'altra finestra, avviare il programma del drone:
   ```powershell
   python drone/main.py
   ```
5. Accendere l'orologio. Nella finestra del broker deve comparire `New client connected from 192.168.1.x` e sull'LCD `Connessione` / `stabilita`.

## Problemi

Se l'orologio non si collega, la seconda riga dell'LCD, sotto `Connessione`, indica dove si è fermato. Lo stesso messaggio, con il codice numerico, compare nel monitor seriale dell'Arduino IDE a 115200 baud.

| LCD, seconda riga | Monitor seriale | Cosa fare |
|---|---|---|
| `assente` | `stato 1` | accendere il router e verificare che `WIFI_SSID` sia uguale all'SSID del router |
| `Password errata` | `stato 4` | verificare che `WIFI_PASS` sia uguale alla password del router |
| `in corso...` per più di 20 s | `stato 0` per più di 20 s | riavviare il router |
| `Broker assente` | `codice -2` o `codice -4` | verificare che il broker sia avviato (sezione 3, punto 3), che il PC abbia `192.168.1.2` e che le regole del firewall esistano (sezione 2, punto 3) |
| `persa` | `connessione persa da 15 s` | verificare che il router sia acceso e il broker avviato; l'orologio si ricollega da solo |

Se il caricamento del firmware si interrompe con `No DFU capable USB device`, installare Arduino ESP32 Boards (sezione 2, punto 5).
