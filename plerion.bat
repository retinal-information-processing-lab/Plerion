@echo off
:: 1. Localisation de Conda
set CONDA_PATH=%USERPROFILE%\anaconda3\Scripts\activate.bat
if not exist "%CONDA_PATH%" set CONDA_PATH=%USERPROFILE%\miniconda3\Scripts\activate.bat

:: 2. Activation de l'environnement
call "%CONDA_PATH%" plerion

:: 3. Navigation dans le dossier du script
cd /d "%~dp0"

:: 4. Lancement silencieux (PySide6 GUI)
start "" pythonw "plerion_qtgui.py"

:: 5. Fermeture immédiate de la console
exit
