// Windows shows a process by its own executable: name (FileDescription) and
// icon. The app runs inside the official, PSF-signed pythonw.exe, which must
// not be edited, so Task Manager said "Python" and the right-click menu showed
// the Python icon. This tiny launcher carries the Coletor's name and fox icon,
// starts pythonw.exe beside it and stays as its parent until it exits.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;

[assembly: AssemblyTitle("Coletor de Frequência")]
[assembly: AssemblyProduct("Coletor de Frequência")]
[assembly: AssemblyCompany("Ecossistema Escolar")]
[assembly: AssemblyDescription("Coletor de Frequência")]
[assembly: AssemblyVersion("0.4.0.0")]
[assembly: AssemblyFileVersion("0.4.0.0")]

static class Launcher
{
    const string Module = "coletor.portable";

    static string Quote(string value)
    {
        if (value.Length > 0 && value.IndexOfAny(new[] { ' ', '\t', '"' }) < 0) return value;
        var text = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\') { slashes++; continue; }
            text.Append('\\', c == '"' ? slashes * 2 + 1 : slashes);
            slashes = 0;
            text.Append(c);
        }
        return text.Append('\\', slashes * 2).Append('"').ToString();
    }

    [STAThread]
    static int Main(string[] args)
    {
        string folder = AppDomain.CurrentDomain.BaseDirectory;
        var line = new StringBuilder("-B -m " + Module);
        foreach (string arg in args) line.Append(' ').Append(Quote(arg));
        var start = new ProcessStartInfo(Path.Combine(folder, "pythonw.exe"), line.ToString())
        {
            WorkingDirectory = folder,
            UseShellExecute = false,
        };
        using (Process child = Process.Start(start))
        {
            child.WaitForExit();
            return child.ExitCode;
        }
    }
}
