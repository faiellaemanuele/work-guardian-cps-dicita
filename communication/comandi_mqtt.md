Per far funzionare i comandi bisogna entrare nella cartella del progetto
(`work-guardian-cps`): basta cliccare con il tasto destro sulla cartella e
scegliere **Apri nel terminale**.

## Missione

**Avvio**

```powershell
& "C:\Program Files\Mosquitto\mosquitto_pub.exe" --% -h 127.0.0.1 -t cantiere/allarmi -q 1 -r -m "{\"source\":\"drone\",\"tipo\":\"AVVIO_MISSIONE\"}"
```

**Fine**

```powershell
& "C:\Program Files\Mosquitto\mosquitto_pub.exe" --% -h 127.0.0.1 -t cantiere/allarmi -q 1 -r -m "{\"source\":\"drone\",\"tipo\":\"FINE_MISSIONE\"}"
```

## Allarmi DPI

**Elmetto**

```powershell
& "C:\Program Files\Mosquitto\mosquitto_pub.exe" --% -h 127.0.0.1 -t cantiere/allarmi -q 1 -m "{\"source\":\"drone\",\"tipo\":\"DPI_MANCANTE\",\"dettaglio\":\"Elmetto\"}"
```

**Occhiali**

```powershell
& "C:\Program Files\Mosquitto\mosquitto_pub.exe" --% -h 127.0.0.1 -t cantiere/allarmi -q 1 -m "{\"source\":\"drone\",\"tipo\":\"DPI_MANCANTE\",\"dettaglio\":\"Occhiali\"}"
```

**Gilet**

```powershell
& "C:\Program Files\Mosquitto\mosquitto_pub.exe" --% -h 127.0.0.1 -t cantiere/allarmi -q 1 -m "{\"source\":\"drone\",\"tipo\":\"DPI_MANCANTE\",\"dettaglio\":\"Gilet\"}"
```

**Scarpe**

```powershell
& "C:\Program Files\Mosquitto\mosquitto_pub.exe" --% -h 127.0.0.1 -t cantiere/allarmi -q 1 -m "{\"source\":\"drone\",\"tipo\":\"DPI_MANCANTE\",\"dettaglio\":\"Scarpe\"}"
```

**Tutti insieme**

```powershell
& "C:\Program Files\Mosquitto\mosquitto_pub.exe" --% -h 127.0.0.1 -t cantiere/allarmi -q 1 -m "{\"source\":\"drone\",\"tipo\":\"DPI_MANCANTE\",\"dettaglio\":\"Elmetto, Occhiali, Gilet, Scarpe\"}"
```

**DPI di nuovo presenti**

```powershell
& "C:\Program Files\Mosquitto\mosquitto_pub.exe" --% -h 127.0.0.1 -t cantiere/allarmi -q 1 -m "{\"source\":\"drone\",\"tipo\":\"DPI_OK\"}"
```

## Area vietata

**Ingresso**

```powershell
& "C:\Program Files\Mosquitto\mosquitto_pub.exe" --% -h 127.0.0.1 -t cantiere/allarmi -q 1 -m "{\"source\":\"drone\",\"tipo\":\"AREA_VIETATA\"}"
```

**Area di nuovo libera**

```powershell
& "C:\Program Files\Mosquitto\mosquitto_pub.exe" --% -h 127.0.0.1 -t cantiere/allarmi -q 1 -m "{\"source\":\"drone\",\"tipo\":\"AREA_OK\"}"
```
