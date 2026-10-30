using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Windows.Forms;

// Network-only workaround. Does not load, inject into, or patch the game.
internal static class OfflineLauncher
{
    private static readonly object LogLock = new object();
    private static StreamWriter log;
    private static int rejected;
    private static volatile bool stopping;
    private static readonly byte[] Refusal = Encoding.ASCII.GetBytes(
        "HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");

    private static void Log(string message)
    {
        lock (LogLock)
        {
            if (log != null) log.WriteLine(DateTime.UtcNow.ToString("o") + " " + message);
        }
    }

    private static void Reject(object item)
    {
        using (TcpClient client = (TcpClient)item)
        {
            try
            {
                client.ReceiveTimeout = 1500;
                client.SendTimeout = 1500;
                client.NoDelay = true;
                NetworkStream stream = client.GetStream();
                byte[] bytes = new byte[8192];
                int count = 0;
                bool headerComplete = false;
                while (count < bytes.Length && !headerComplete)
                {
                    int n = stream.Read(bytes, count, bytes.Length - count);
                    if (n == 0) return;
                    int start = Math.Max(0, count - 3);
                    count += n;
                    for (int i = start; i + 3 < count; i++)
                    {
                        if (bytes[i] == 13 && bytes[i+1] == 10 && bytes[i+2] == 13 && bytes[i+3] == 10)
                        { headerComplete = true; break; }
                    }
                }
                // Never retain request headers, URLs, bodies or authentication data.
                stream.Write(Refusal, 0, Refusal.Length);
                Log("Rejected request #" + Interlocked.Increment(ref rejected));
            }
            catch (IOException) { }
            catch (SocketException) { }
        }
    }

    private static void Accept(TcpListener listener)
    {
        while (!stopping)
        {
            try { ThreadPool.QueueUserWorkItem(Reject, listener.AcceptTcpClient()); }
            catch (SocketException) { if (!stopping) Log("Listener socket error"); }
            catch (ObjectDisposedException) { break; }
        }
    }

    [STAThread]
    private static void Main(string[] args)
    {
        TcpListener listener = null;
        Thread acceptThread = null;
        bool created;
        using (Mutex single = new Mutex(true, "Local\\DS2-OfflineLauncher", out created))
        {
            if (!created) { MessageBox.Show("Offline launcher is already running.", "Darksiders II"); return; }
            try
            {
                bool selfTest = GameLocator.Has(args,"--self-test");
                string root = AppDomain.CurrentDomain.BaseDirectory;
                string exe = selfTest ? null : GameLocator.Resolve(args);
                if (!selfTest && Process.GetProcessesByName("Darksiders2").Length != 0)
                    throw new InvalidOperationException("Exit Darksiders II before starting Offline mode.");
                if (!selfTest && !File.Exists(exe)) throw new FileNotFoundException("Darksiders2.exe is missing.", exe);
                string research = GameLocator.DataRoot;
                Directory.CreateDirectory(research);
                log = new StreamWriter(Path.Combine(research, selfTest ? "offline-selftest.log" : "offline-session.log"), false, Encoding.UTF8);
                log.AutoFlush = true;
                listener = new TcpListener(IPAddress.Loopback, 0);
                listener.Start(32);
                int port = ((IPEndPoint)listener.LocalEndpoint).Port;
                TcpListener local = listener;
                acceptThread = new Thread(delegate() { Accept(local); });
                acceptThread.IsBackground = true;
                acceptThread.Start();
                string proxy = "http://127.0.0.1:" + port;
                Log("Loopback rejection proxy started on port " + port);
                if (selfTest)
                {
                    Stopwatch elapsed = Stopwatch.StartNew();
                    using (TcpClient test = new TcpClient("127.0.0.1", port))
                    {
                        test.ReceiveTimeout = 3000;
                        NetworkStream stream = test.GetStream();
                        byte[] request = Encoding.ASCII.GetBytes("CONNECT ds2.thqconnect.com:8443 HTTP/1.1\r\nHost: ds2.thqconnect.com\r\n\r\n");
                        stream.Write(request, 0, request.Length);
                        using (StreamReader reader = new StreamReader(stream, Encoding.ASCII))
                        {
                            if (reader.ReadLine() != "HTTP/1.1 503 Service Unavailable") throw new IOException("Wrong proxy response.");
                        }
                    }
                    Log("SELFTEST PASS: local CONNECT refused in " + elapsed.ElapsedMilliseconds + " ms");
                    return;
                }
                ProcessStartInfo start = new ProcessStartInfo(exe);
                start.UseShellExecute = false;
                start.WorkingDirectory = Path.GetDirectoryName(exe);
                start.EnvironmentVariables["http_proxy"] = proxy;
                start.EnvironmentVariables["https_proxy"] = proxy;
                start.EnvironmentVariables["ALL_PROXY"] = proxy;
                start.EnvironmentVariables["NO_PROXY"] = "";
                start.EnvironmentVariables["SteamAppId"] = "50650";
                start.EnvironmentVariables["SteamGameId"] = "50650";
                using (Process game = Process.Start(start))
                {
                    Log("Game started. PID=" + game.Id);
                    game.WaitForExit();
                    Log("Game exited. ExitCode=" + game.ExitCode + "; rejected=" + rejected);
                }
            }
            catch (Exception e)
            {
                Log("ERROR: " + e.Message);
                Environment.ExitCode = 1;
                if(!GameLocator.Has(args,"--quiet"))MessageBox.Show(e.Message, "Darksiders II Offline", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            finally
            {
                stopping = true;
                if (listener != null) listener.Stop();
                if (acceptThread != null) acceptThread.Join(2000);
                lock (LogLock) { if (log != null) { log.Dispose(); log = null; } }
                single.ReleaseMutex();
            }
        }
    }
}
