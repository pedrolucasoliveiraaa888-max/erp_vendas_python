import sys
import os

# Proteção obrigatória para PyInstaller com --windowed no Windows
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import threading
import time
import webbrowser
import uvicorn
from app import app

def abrir_navegador():
    time.sleep(1.5)  # Aguarda o servidor iniciar
    webbrowser.open("http://127.0.0.1:8000")

if __name__ == "__main__":
    # Inicia o navegador em uma thread separada
    threading.Thread(target=abrir_navegador, daemon=True).start()
    
    # Inicia o servidor ignorando o manipulador de logs do terminal
    uvicorn.run(app, host="127.0.0.1", port=8000, log_config=None)