' Lanza la GUI de MathOCR (MathOCRSimple) sin consola.
' MathOCRSimple.exe lo genera 'pip install -e .' como gui-script (arranca con
' pythonw, sin ventana). Este .vbs queda solo como acceso directo cómodo.
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Renzo\Proyectos\MathOCR"
WshShell.Run """C:\Renzo\Proyectos\MathOCR\venv\Scripts\MathOCRSimple.exe""", 0, False
