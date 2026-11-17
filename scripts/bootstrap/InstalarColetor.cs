// "Instalar Coletor.exe": always installs the newest Coletor (owner request 16/11/2026).
// It reads the latest GitHub Release, accepts it only when the Release and its files were made by the
// publishing workflow (github-actions[bot], as app/coletor/updater.py does), downloads the installer,
// checks size, SHA-256 and PE header against atualizacao.json and the school's signature, and opens it.
// Built, signed and published with every Release by .github/workflows/checks.yml (scripts/bootstrap/build.ps1);
// nothing is installed or written besides the downloaded installer in %TEMP%.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
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
    // SHA-256 of the school's code-signing certificate: the same list as SIGNERS in app/coletor/updater.py.
    static readonly string[] Signers = { "929ee6187af8e05d028893cb57d34400c7ec5762c3146763fafb6321dce4ceb0" };

    class Failure : Exception { public Failure(string message) : base(message) { } }

    static Label status;
    static ProgressBar bar;
    static Form window;

    [STAThread]
    static int Main(string[] args)
    {
        // Tests only: 0 when the file carries the school's signature, 3 another intact one, 4 none.
        if (args.Length == 2 && args[0] == "--conferir")
        {
            string who = Signer(args[1]);
            return who == null ? 4 : Array.IndexOf(Signers, who) < 0 ? 3 : 0;
        }
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
        if (File.Exists(target) && Matches(target, sha, size) && Array.IndexOf(Signers, Signer(target)) >= 0) return target;
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
        // The Release's own hash only proves the download is whole; the signature proves who built it.
        if (Array.IndexOf(Signers, Signer(partial)) < 0)
        {
            File.Delete(partial);
            throw new Failure("O instalador baixado não tem a assinatura da escola. Nada foi instalado.");
        }
        if (File.Exists(target)) File.Delete(target);
        File.Move(partial, target);
        Say("Abrindo o instalador…", 100);
        return target;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct TrustFile { public int Size; public string Path; public IntPtr File, Subject; }

    [StructLayout(LayoutKind.Sequential)]
    struct TrustData
    {
        public int Size; public IntPtr Policy, Sip; public int Ui, Revocation, Choice; public IntPtr File;
        public int Action; public IntPtr State, Url; public int Flags, Context; public IntPtr Settings;
    }

    [DllImport("wintrust.dll", ExactSpelling = true)]
    static extern int WinVerifyTrust(IntPtr window, ref Guid action, ref TrustData data);
    [DllImport("wintrust.dll", ExactSpelling = true)]
    static extern IntPtr WTHelperProvDataFromStateData(IntPtr state);
    [DllImport("wintrust.dll", ExactSpelling = true)]
    static extern IntPtr WTHelperGetProvSignerFromChain(IntPtr provider, int signer, bool counter, int index);

    // SHA-256 (hex) of the certificate whose Authenticode signature the file carries intact, else null:
    // the same check as signer() in app/coletor/updater.py. Windows compares the signature with the
    // file (no dialog, no network); the school's certificate is self-signed, so its root is unknown.
    static string Signer(string path)
    {
        var action = new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");
        var file = new TrustFile { Size = Marshal.SizeOf(typeof(TrustFile)), Path = path };
        IntPtr pointer = Marshal.AllocHGlobal(file.Size);
        Marshal.StructureToPtr(file, pointer, false);
        var data = new TrustData { Size = Marshal.SizeOf(typeof(TrustData)), Ui = 2, Choice = 1, File = pointer, Action = 1, Flags = 0x1010 };
        var none = new IntPtr(-1);
        try
        {
            uint verdict = unchecked((uint)WinVerifyTrust(none, ref action, ref data));
            if (verdict != 0 && verdict != 0x800B0109) return null;
            IntPtr provider = WTHelperProvDataFromStateData(data.State);
            IntPtr signer = provider == IntPtr.Zero ? IntPtr.Zero : WTHelperGetProvSignerFromChain(provider, 0, false, 0);
            // CRYPT_PROVIDER_SGNR: size, time, count, chain; CRYPT_PROVIDER_CERT: size, certificate.
            if (signer == IntPtr.Zero || Marshal.ReadInt32(signer, 12) < 1) return null;
            IntPtr chain = Marshal.ReadIntPtr(signer, 16);
            IntPtr certificate = chain == IntPtr.Zero ? IntPtr.Zero : Marshal.ReadIntPtr(chain, IntPtr.Size);
            if (certificate == IntPtr.Zero) return null;
            using (var hash = SHA256.Create())
            {
                var text = new StringBuilder();
                foreach (byte b in hash.ComputeHash(new X509Certificate2(certificate).RawData)) text.Append(b.ToString("x2"));
                return text.ToString();
            }
        }
        finally
        {
            data.Action = 2; // Close the verification state.
            WinVerifyTrust(none, ref action, ref data);
            Marshal.DestroyStructure(pointer, typeof(TrustFile));
            Marshal.FreeHGlobal(pointer);
        }
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
