// "Instalar Coletor.exe" (instalador/): always installs the newest Coletor (owner request 16/11/2026).
// It reads the latest GitHub Release, accepts it only when the Release and its files were made by the
// publishing workflow (github-actions[bot], as app/coletor/updater.py does), downloads the installer,
// checks size, SHA-256 and PE header against atualizacao.json and opens it. Built by
// scripts/bootstrap/build.ps1; nothing is installed or written besides the downloaded installer in %TEMP%.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("Instalar Coletor")]
[assembly: AssemblyProduct("Coletor")]
[assembly: AssemblyCompany("Ecossistema Escolar")]
[assembly: AssemblyDescription("Baixa e abre o instalador mais novo do Coletor")]
[assembly: AssemblyVersion("1.0.0.0")]

static class InstalarColetor
{
    const string Api = "https://api.github.com/repos/mcpmieda/coletor/releases/latest";
    const string Publisher = "github-actions[bot]";
    const string Manifest = "atualizacao.json";
    const long MinimumSize = 1000000, MaximumSize = 300L * 1024 * 1024;

    class Failure : Exception { public Failure(string message) : base(message) { } }

    static Label status;
    static ProgressBar bar;
    static Form window;

    [STAThread]
    static int Main(string[] args)
    {
        bool open = Array.IndexOf(args, "--sem-abrir") < 0; // Checks without opening (tests only).
        ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
        Application.EnableVisualStyles();
        window = new Form { Text = "Instalar Coletor", Width = 420, Height = 140, FormBorderStyle = FormBorderStyle.FixedDialog,
                            MaximizeBox = false, MinimizeBox = false, StartPosition = FormStartPosition.CenterScreen };
        try { window.Icon = Icon(); } catch { }
        status = new Label { Text = "Procurando a versão mais nova…", Left = 16, Top = 16, Width = 372 };
        bar = new ProgressBar { Left = 16, Top = 48, Width = 372, Height = 18, Style = ProgressBarStyle.Marquee };
        window.Controls.Add(status);
        window.Controls.Add(bar);
        int code = 1;
        window.Shown += delegate
        {
            new Thread(delegate ()
            {
                try
                {
                    string setup = Download();
                    if (open) Process.Start(new ProcessStartInfo(setup) { UseShellExecute = true, WorkingDirectory = Path.GetDirectoryName(setup) });
                    code = 0;
                }
                catch (Failure error) { Show(error.Message); }
                catch (WebException) { Show("Não foi possível baixar o Coletor. Confira a internet e tente de novo."); }
                catch (Exception) { Show("Não foi possível preparar a instalação do Coletor. Tente de novo."); }
                window.BeginInvoke((MethodInvoker)window.Close);
            }) { IsBackground = true }.Start();
        };
        Application.Run(window);
        return code;
    }

    static System.Drawing.Icon Icon()
    {
        return System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath);
    }

    static void Show(string message)
    {
        window.Invoke((MethodInvoker)delegate { MessageBox.Show(window, message, "Instalar Coletor", MessageBoxButtons.OK, MessageBoxIcon.Error); });
    }

    static void Say(string text, int percent)
    {
        window.BeginInvoke((MethodInvoker)delegate
        {
            status.Text = text;
            if (percent >= 0) { bar.Style = ProgressBarStyle.Continuous; bar.Value = Math.Min(100, percent); }
        });
    }

    static WebClient Client()
    {
        var client = new WebClient();
        client.Headers[HttpRequestHeader.UserAgent] = "Coletor-instalador";
        return client;
    }

    static Dictionary<string, object> Object(object value)
    {
        var map = value as Dictionary<string, object>;
        if (map == null) throw new Failure("A versão publicada não pôde ser conferida.");
        return map;
    }

    static string Text(Dictionary<string, object> map, string key)
    {
        object value;
        return map.TryGetValue(key, out value) ? value as string : null;
    }

    static string Login(Dictionary<string, object> map, string key)
    {
        object value;
        return map.TryGetValue(key, out value) && value is Dictionary<string, object> ? Text((Dictionary<string, object>)value, "login") : null;
    }

    static string Download()
    {
        var json = new JavaScriptSerializer();
        Dictionary<string, object> release;
        using (var client = Client()) release = Object(json.DeserializeObject(client.DownloadString(Api)));
        string tag = Text(release, "tag_name") ?? "";
        object draft;
        if (!Regex.IsMatch(tag, @"\Av\d{1,5}\.\d{1,5}\.\d{1,5}\z") || !release.TryGetValue("draft", out draft) || !(draft is bool) || (bool)draft)
            throw new Failure("A versão publicada não pôde ser conferida.");
        if (Login(release, "author") != Publisher)
            throw new Failure("A versão mais nova não foi publicada pelo processo oficial. Nada foi instalado.");
        string version = tag.Substring(1), name = "COLETOR-v" + version + ".exe";
        var assets = new Dictionary<string, Dictionary<string, object>>();
        foreach (object item in (release["assets"] as IEnumerable) ?? new object[0])
        {
            var asset = item as Dictionary<string, object>;
            if (asset != null && Text(asset, "name") != null) assets[Text(asset, "name")] = asset;
        }
        foreach (string file in new[] { name, Manifest })
            if (!assets.ContainsKey(file) || Text(assets[file], "state") != "uploaded" || Login(assets[file], "uploader") != Publisher)
                throw new Failure("A versão mais nova não foi publicada pelo processo oficial. Nada foi instalado.");

        Dictionary<string, object> manifest;
        using (var client = Client())
        {
            string text = client.DownloadString(Text(assets[Manifest], "browser_download_url"));
            if (text.Length > 4096) throw new Failure("A versão publicada não pôde ser conferida.");
            manifest = Object(json.DeserializeObject(text));
        }
        string sha = Text(manifest, "sha256") ?? "";
        object sizeValue;
        long size = manifest.TryGetValue("tamanho", out sizeValue) && (sizeValue is int || sizeValue is long) ? Convert.ToInt64(sizeValue) : -1;
        if (Text(manifest, "versao") != version || Text(manifest, "arquivo") != name || !Regex.IsMatch(sha, @"\A[0-9a-f]{64}\z")
            || size < MinimumSize || size > MaximumSize)
            throw new Failure("A versão publicada não pôde ser conferida.");

        string folder = Path.Combine(Path.GetTempPath(), "Coletor");
        Directory.CreateDirectory(folder);
        string target = Path.Combine(folder, "COLETOR v" + version + ".exe"), partial = target + ".part";
        if (File.Exists(target) && Matches(target, sha, size)) return target;
        Say("Baixando o Coletor " + version + "…", 0);
        using (var client = Client())
        {
            client.DownloadProgressChanged += (sender, e) =>
                Say("Baixando o Coletor " + version + "… " + (e.BytesReceived / 1048576) + " de " + (size / 1048576) + " MB",
                    (int)(e.BytesReceived * 100 / size));
            var done = new ManualResetEvent(false);
            Exception failed = null;
            client.DownloadFileCompleted += (sender, e) => { failed = e.Error; done.Set(); };
            client.DownloadFileAsync(new Uri(Text(assets[name], "browser_download_url")), partial);
            done.WaitOne();
            if (failed is WebException) throw (WebException)failed;
            if (failed != null) throw new Failure("Não foi possível baixar o Coletor. Tente de novo.");
        }
        if (!Matches(partial, sha, size))
        {
            File.Delete(partial);
            throw new Failure("O arquivo baixado não confere com o publicado. Nada foi instalado; tente de novo.");
        }
        if (File.Exists(target)) File.Delete(target);
        File.Move(partial, target);
        Say("Abrindo o instalador…", 100);
        return target;
    }

    static bool Matches(string path, string sha, long size)
    {
        if (new FileInfo(path).Length != size) return false;
        using (var stream = File.OpenRead(path))
        {
            var header = new byte[2];
            if (stream.Read(header, 0, 2) != 2 || header[0] != (byte)'M' || header[1] != (byte)'Z') return false;
            stream.Position = 0;
            using (var hash = SHA256.Create())
            {
                var text = new StringBuilder();
                foreach (byte b in hash.ComputeHash(stream)) text.Append(b.ToString("x2"));
                return text.ToString() == sha;
            }
        }
    }
}
