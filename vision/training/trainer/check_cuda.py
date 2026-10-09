"""Verifica della disponibilità di CUDA per PyTorch.

Lo script mostra la versione di PyTorch installata e controlla se
l'addestramento può utilizzare una GPU NVIDIA tramite CUDA.

Vengono distinti tre casi:
- PyTorch installato senza supporto CUDA;
- PyTorch compilato con CUDA, ma senza GPU disponibile;
- GPU CUDA disponibile e utilizzabile.

Quando sono presenti una o più GPU, per ciascuna vengono mostrati nome e
memoria video totale.
"""

import sys

import torch


def _ensure_utf8_console() -> None:
    """Configura stdout e stderr in UTF-8 quando il runtime lo consente."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue

        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


_ensure_utf8_console()

print(f"Versione di PyTorch: {torch.__version__}")

if torch.version.cuda is None:
    print(
        "Questa installazione è solo per CPU: "
        "PyTorch è stato compilato senza CUDA."
    )
    print("L'addestramento userà la CPU e sarà molto più lento.")
    print(
        "Per usare la GPU va reinstallato PyTorch "
        "nella versione con supporto CUDA."
    )

elif not torch.cuda.is_available():
    print(
        f"PyTorch è compilato per CUDA {torch.version.cuda}, "
        "ma non vede nessuna GPU."
    )
    print("L'addestramento userà la CPU e sarà molto più lento.")
    print(
        "Può mancare una GPU NVIDIA oppure i driver "
        "potrebbero non essere aggiornati."
    )

else:
    print(
        f"PyTorch è compilato per CUDA {torch.version.cuda} "
        "e la GPU è utilizzabile."
    )

    for i in range(torch.cuda.device_count()):
        nome = torch.cuda.get_device_name(i)
        byte = torch.cuda.get_device_properties(i).total_memory
        memoria = f"{byte / (1024 ** 3):.1f}".replace(".", ",")

        print(f"  scheda {i}: {nome} ({memoria} GB)")
        