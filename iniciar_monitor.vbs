Set WshShell = CreateObject("WScript.Shell")
' Substitua o caminho completo para o Python e para o seu script
WshShell.Run "C:\Users\DOUGLAS\AppData\Local\Programs\Python\Python313\python.exe C:\Users\DOUGLAS\Documents\programas\python\licitacoes.py", 0, False
Set WshShell = Nothing