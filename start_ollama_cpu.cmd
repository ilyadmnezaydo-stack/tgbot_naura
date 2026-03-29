@echo off
setlocal

set OLLAMA_HOST=127.0.0.1:11434
set OLLAMA_LLM_LIBRARY=cpu

"C:\Users\tyryt\AppData\Local\Programs\Ollama\ollama.exe" serve
