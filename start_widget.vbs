' Starts pc_widget.py in the background with no console window.
' Keep this file in the same folder as pc_widget.py.
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
script = """" & folder & "\pc_widget.py"""
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = folder

On Error Resume Next
sh.Run "pythonw " & script, 0, False
If Err.Number <> 0 Then
    Err.Clear
    sh.Run "pyw " & script, 0, False
End If
