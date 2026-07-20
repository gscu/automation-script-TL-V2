' Launches the Bandwidth Report Manager desktop app with NO console window.
' Double-click this file to open the app. It finds pythonw.exe automatically.
Option Explicit

Dim fso, shell, here, gui, py, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
gui = here & "\bandwidth_report_manager.py"

' Prefer pythonw.exe (no console). Try PATH, then the py launcher.
py = "pythonw.exe"

cmd = """" & py & """ """ & gui & """"
On Error Resume Next
shell.CurrentDirectory = here
shell.Run cmd, 0, False   ' 0 = hidden window, no console flash
If Err.Number <> 0 Then
    ' Fall back to the Windows py launcher in windowed mode.
    Err.Clear
    shell.Run "pyw.exe """ & gui & """", 0, False
End If
If Err.Number <> 0 Then
    ' Last resort: plain py launcher (there is no "-w" flag; the hidden
    ' window style already keeps the console out of sight).
    Err.Clear
    shell.Run "py.exe """ & gui & """", 0, False
End If
On Error Goto 0
