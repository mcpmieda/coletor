// This parent has the Coletor name/icon. Its unmodified Python child keeps
// Python's own identity and PSF signature; neither is inherited by this EXE.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.ComponentModel;
using System.Windows.Forms;

[assembly: AssemblyTitle("Coletor de Frequência")]
[assembly: AssemblyProduct("Coletor de Frequência")]
[assembly: AssemblyCompany("Ecossistema Escolar")]
[assembly: AssemblyDescription("Coletor de Frequência")]
// Version attributes are generated from app/coletor/__init__.py during build.

static class Launcher
{
    const string Module = "coletor.portable";

    static int Failed(string code, int exitCode, bool background)
    {
        // Never record arguments, exception messages, user paths or Python output.
        try
        {
            string folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                         "EcossistemaEscolar", "ColetorFrequencia");
            Directory.CreateDirectory(folder);
            string log = Path.Combine(folder, "launcher.log");
            if (File.Exists(log) && new FileInfo(log).Length > 65536) File.Delete(log);
            File.AppendAllText(log, DateTime.UtcNow.ToString("o") + " " + code + " exit=" + exitCode + Environment.NewLine,
                               Encoding.UTF8);
        }
        catch { /* Diagnostics must never replace the original failure. */ }
        if (!background)
        {
            try
            {
                MessageBox.Show("Não foi possível iniciar o Coletor. Reinstale o pacote completo ou peça ajuda.\n\n" +
                                "Registro de suporte: %LOCALAPPDATA%\\EcossistemaEscolar\\ColetorFrequencia\\launcher.log",
                                "Coletor de Frequência", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            catch { /* Preserve the original exit code even if no desktop exists. */ }
        }
        return exitCode;
    }

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
        bool background = Array.Exists(args, arg => String.Equals(arg, "--background", StringComparison.Ordinal));
        string folder = AppDomain.CurrentDomain.BaseDirectory;
        string runtime = Path.Combine(folder, "pythonw.exe");
        if (!File.Exists(runtime)) return Failed("runtime-missing", 2, background);
        try
        {
            var line = new StringBuilder("-B -m " + Module);
            foreach (string arg in args) line.Append(' ').Append(Quote(arg));
            var start = new ProcessStartInfo(runtime, line.ToString())
            {
                WorkingDirectory = folder,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            using (Process child = Process.Start(start))
            {
                if (child == null) return Failed("runtime-not-started", 1, background);
                child.WaitForExit();
                return child.ExitCode == 0 ? 0 : Failed("runtime-exit", child.ExitCode, background);
            }
        }
        catch (Win32Exception error)
        {
            if (error.NativeErrorCode == 5) return Failed("runtime-access-denied", 5, background);
            return Failed("runtime-start-failed", error.NativeErrorCode > 0 ? error.NativeErrorCode : 1, background);
        }
        catch { return Failed("launcher-failed", 1, background); }
    }
}
