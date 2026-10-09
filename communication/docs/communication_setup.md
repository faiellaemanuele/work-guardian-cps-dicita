# Configurazione e avvio della comunicazione

La comunicazione del sistema utilizza due reti distinte:

```text
Tello  ◄── Wi-Fi ──►  PC (drone + Mosquitto)  ◄── Ethernet ──►  Router  ◄── Wi-Fi ──►  Smartwatch
```

Il PC è quindi collegato contemporaneamente:

- tramite Wi-Fi alla rete generata dal Tello;
- tramite Ethernet al router utilizzato dallo smartwatch.

Mosquitto viene eseguito sul PC e svolge il ruolo di broker MQTT. Il programma
del drone lo raggiunge localmente tramite `127.0.0.1`, mentre lo smartwatch lo
raggiunge attraverso l'indirizzo Ethernet fisso `192.168.1.2`.

I comandi riportati di seguito devono essere eseguiti in PowerShell aperto come
amministratore quando richiedono privilegi elevati.

## 1. Configurazione del router

Questa procedura è necessaria dopo un reset di fabbrica del router.

1. Collegare il PC a una porta LAN del router tramite cavo Ethernet.
2. Aprire nel browser `http://192.168.1.1`.
3. Se compare la procedura guidata `Connection Type`, ignorarla.
4. In **Wireless Settings → Configuration**, impostare l'SSID:

   ```text
   WorkGuardian
   ```

   Il valore deve coincidere con `WIFI_SSID` definito in
   `wearable/smartwatch/network_config.h`.

5. In **Wireless Settings → Encryption**, selezionare `WPA-PSK (no server)` e
   impostare come password il valore di `WIFI_PASS` presente nello stesso file.

## 2. Configurazione del PC

Questa procedura deve essere eseguita una volta per ogni computer utilizzato.

### 2.1 Indirizzo Ethernet fisso

Collegare la scheda Ethernet del PC a una porta LAN del router, non alla porta
WAN.

Dalla pagina `http://192.168.1.1`, aprire **LAN Settings → DHCP Client Lists**
e riservare al PC l'indirizzo:

```text
192.168.1.2
```

Per il primo PC:

1. individuare la riga con indirizzo `192.168.1.2`;
2. selezionare `Fix`;
3. premere `Apply`.

Se il PC viene sostituito e l'indirizzo è già associato a un altro computer:

1. premere `Edit` sulla riga relativa a `192.168.1.2`;
2. sostituire il MAC address con quello della scheda Ethernet del nuovo PC;
3. premere `Apply`.

Il MAC address può essere letto con:

```powershell
Get-NetAdapter
```

Dopo la modifica, rinnovare la configurazione di rete:

```powershell
ipconfig /release
ipconfig /renew
```

Infine verificare con `ipconfig` che la scheda Ethernet abbia indirizzo
`192.168.1.2`.

### 2.2 Firewall di Windows

Aprire le porte utilizzate dal broker MQTT e dai flussi provenienti dal Tello:

```powershell
New-NetFirewallRule -DisplayName "WorkGuardian - Mosquitto" -Direction Inbound -Protocol TCP -LocalPort 1883 -RemoteAddress 192.168.1.0/24 -Action Allow
New-NetFirewallRule -DisplayName "WorkGuardian - Tello" -Direction Inbound -Protocol UDP -LocalPort 8890,11111 -RemoteAddress 192.168.10.1 -Action Allow
Set-NetFirewallProfile -Profile Public,Private -Enabled True
```

Le porte interessate sono:

- `1883/TCP`: broker MQTT;
- `8890/UDP`: telemetria del Tello;
- `11111/UDP`: flusso video del Tello.

### 2.3 Installazione di Mosquitto

Installare Mosquitto nella cartella predefinita:

```text
C:\Program Files\Mosquitto
```

Impostare il relativo servizio Windows su avvio manuale:

```powershell
Set-Service mosquitto -StartupType Manual
```

Il broker verrà avviato esplicitamente durante la procedura operativa.

### 2.4 Preparazione dello smartwatch

Nell'Arduino IDE:

1. installare da **Boards Manager** `Arduino ESP32 Boards` di Arduino;
2. installare da **Library Manager**:
   - `MAX30100_milan`;
   - `PubSubClient` di Nick O'Leary;
3. in **Tools → Board** selezionare:
   `Arduino ESP32 Boards → Arduino Nano ESP32`;
4. collegare lo smartwatch via USB;
5. aprire `wearable/smartwatch/smartwatch.ino`;
6. caricare il firmware.

## 3. Avvio del sistema

Questa procedura va eseguita a ogni utilizzo.

### 3.1 Router e rete Ethernet

Accendere il router e verificare con:

```powershell
ipconfig
```

che la scheda Ethernet del PC abbia indirizzo:

```text
192.168.1.2
```

### 3.2 Arresto di eventuali istanze di Mosquitto

Chiudere eventuali istanze già attive:

```powershell
net stop mosquitto
taskkill /F /IM mosquitto.exe
```

Se Mosquitto non è già in esecuzione, uno o entrambi i comandi possono
restituire un errore: in questo caso è normale.

### 3.3 Avvio del broker MQTT

Dalla cartella principale del progetto eseguire:

```powershell
& "C:\Program Files\Mosquitto\mosquitto.exe" -c "communication\broker\mqtt_broker.conf" -v
```

Lasciare aperta questa finestra per tutta la durata dell'esecuzione.

Nel terminale deve comparire un messaggio equivalente a:

```text
Opening ipv4 listen socket on port 1883
```

Se Windows richiede l'autorizzazione di rete per Mosquitto, consentire
l'accesso alle reti necessarie.

### 3.4 Avvio del drone

1. Accendere il Tello.
2. Collegare il Wi-Fi del PC alla rete generata dal drone (`TELLO-...`).
3. Aprire una nuova finestra di PowerShell nella radice del progetto.
4. Avviare:

```powershell
python drone/main.py
```

Il programma del drone comunica con il broker tramite `127.0.0.1:1883`, quindi
non dipende dall'interfaccia Ethernet per il collegamento locale a Mosquitto.

### 3.5 Avvio dello smartwatch

Accendere lo smartwatch.

Quando la connessione è corretta:

- nella finestra di Mosquitto compare un nuovo client proveniente dalla rete
  `192.168.1.x`;
- sul display dello smartwatch compare:

```text
Connessione
stabilita
```

## 4. Diagnostica

Se lo smartwatch non riesce a collegarsi, la seconda riga del display indica
la fase in cui la connessione si è arrestata. Lo stesso evento viene riportato
nel monitor seriale dell'Arduino IDE a `115200 baud`.

| Display | Monitor seriale | Verifica |
|---|---|---|
| `assente` | `stato 1` | Accendere il router e verificare che `WIFI_SSID` coincida con l'SSID configurato. |
| `Password errata` | `stato 4` | Verificare che `WIFI_PASS` coincida con la password del router. |
| `in corso...` per più di 20 s | `stato 0` per più di 20 s | Riavviare il router. |
| `Broker assente` | `codice -2` o `codice -4` | Verificare che Mosquitto sia avviato, che il PC abbia `192.168.1.2` e che la regola firewall sulla porta 1883 sia presente. |
| `persa` | `connessione persa da 15 s` | Verificare router e broker. Lo smartwatch tenta automaticamente la riconnessione. |

Se il caricamento del firmware termina con:

```text
No DFU capable USB device
```

verificare che `Arduino ESP32 Boards` sia installato correttamente nell'Arduino
IDE.
