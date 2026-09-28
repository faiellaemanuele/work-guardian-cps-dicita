# Avvio della comunicazione

```
Tello  ◄── Wi-Fi ──►  PC (Mosquitto)  ◄── Ethernet ──►  Router  ◄── Wi-Fi ──►  Orologio
```

## 1. Router (solo dopo un reset di fabbrica)

Router 3Com OfficeConnect, pagina `http://192.168.1.1` con il PC collegato via cavo.
Ignorare la procedura guidata "Connection Type".

1. **Wireless Settings → Configuration**: SSID `WorkGuardian`.
2. **Wireless Settings → Encryption**: `WPA-PSK (no server)`, password uguale a `WIFI_PASS` del firmware.

## 2. PC (una volta per ogni computer)

1. Collegare il cavo a una porta **LAN** del router, non WAN.

2. Riservare `192.168.1.2` al PC: in `http://192.168.1.1` → **LAN Settings**, tabella **DHCP Client Lists**.
   - **Primo PC**: sulla riga del PC con `192.168.1.2` spuntare **Fix** e premere **Apply**.
   - **Cambio PC** (la riga `192.168.1.2` è già fissa su un altro computer):
     premere **Edit** su quella riga, inserire il MAC della scheda Ethernet del nuovo PC
     (colonna `MacAddress` di `Get-NetAdapter`) e premere **Apply**. Poi, in PowerShell
     come amministratore:
     ```powershell
     ipconfig /release
     ipconfig /renew
     ```
   - Verificare con `ipconfig` che la scheda Ethernet abbia `192.168.1.2`.

3. Configurare il firewall, in PowerShell come amministratore:
   ```powershell
   New-NetFirewallRule -DisplayName "WorkGuardian - Mosquitto" -Direction Inbound -Protocol TCP -LocalPort 1883 -RemoteAddress 192.168.1.0/24 -Action Allow
   New-NetFirewallRule -DisplayName "WorkGuardian - Tello" -Direction Inbound -Protocol UDP -LocalPort 8890,11111 -RemoteAddress 192.168.10.1 -Action Allow
   Set-NetFirewallProfile -Profile Public,Private -Enabled True
   ```
   Se Windows chiede l'accesso di rete per Mosquitto: spuntare **Reti private** e **Reti pubbliche**, poi **Consenti accesso**. Non premere Annulla.

4. Installare Mosquitto in `C:\Program Files\Mosquitto` e passare il servizio ad avvio manuale, in PowerShell come amministratore:
   ```powershell
   Set-Service mosquitto -StartupType Manual
   ```

5. Per caricare il firmware (`wearable/smartwatch/smartwatch.ino`): nell'Arduino IDE installare **Arduino ESP32 Boards** (di Arduino) e scegliere la scheda *Arduino ESP32 Boards → Arduino Nano ESP32*.

## 3. Avvio (ogni volta)

1. Accendere il router. Verificare con `ipconfig` che la scheda Ethernet abbia `192.168.1.2`.

2. Chiudere eventuali Mosquitto già attivi, in PowerShell come amministratore:
   ```powershell
   net stop mosquitto
   taskkill /F /IM mosquitto.exe
   ```

3. Avviare il broker dalla radice del progetto e lasciare aperta la finestra:
   ```powershell
   & "C:\Program Files\Mosquitto\mosquitto.exe" -c communication\mqtt_broker.conf -v
   ```
   Deve comparire `Opening ipv4 listen socket on port 1883`.

4. Collegare il Wi-Fi del PC al Tello e avviare:
   ```powershell
   python drone/main.py
   ```

5. Accendere l'orologio. Nella finestra del broker deve comparire `New client connected from 192.168.1.x`.

## Problemi

Monitor seriale dell'orologio a 115200 baud:

| Messaggio | Cosa fare |
|---|---|
| `stato 1` | router spento o `WIFI_SSID` errato |
| `stato 4` | `WIFI_PASS` diversa dalla password del router |
| `stato 0` per più di 20 s | riavviare il router |
| `codice -2` | avviare Mosquitto, controllare `192.168.1.2` e le regole del firewall |
| `No DFU capable USB device` al caricamento | installare **Arduino ESP32 Boards** (sezione 2, punto 5) |
