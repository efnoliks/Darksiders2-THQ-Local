using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Management;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class PortableLauncher
{
    private static int port=18086;
    private static string Python {get{return Path.Combine(GameLocator.ModRoot,@"runtime\python.exe");}}
    private static string ServerFile {get{return Path.Combine(GameLocator.ModRoot,"server.py");}}
    private static void Log(string message){try{File.AppendAllText(Path.Combine(GameLocator.DataRoot,"launcher.log"),DateTime.UtcNow.ToString("o")+" "+message+Environment.NewLine);}catch(IOException){}catch(UnauthorizedAccessException){}}
    private static Dictionary<string,object> Health(bool verifyCertificate=true)
    {
        using(TcpClient probe=new TcpClient())
        {
            IAsyncResult connect=probe.BeginConnect("127.0.0.1",port,null,null);
            try{if(!connect.AsyncWaitHandle.WaitOne(4000))throw new IOException("Local port connection timed out.");probe.EndConnect(connect);}
            catch(SocketException e){if(e.SocketErrorCode==SocketError.ConnectionRefused)return null;throw;}
            finally{connect.AsyncWaitHandle.Close();}
        }
        HttpWebRequest request=(HttpWebRequest)WebRequest.Create("http://127.0.0.1:"+port+"/health");
        request.Proxy=null;request.Timeout=1500;request.ReadWriteTimeout=1500;
        using(WebResponse response=request.GetResponse())using(StreamReader reader=new StreamReader(response.GetResponseStream()))
        {
            char[] buffer=new char[8193];int used=0,n;
            while(used<buffer.Length&&(n=reader.Read(buffer,used,buffer.Length-used))>0)used+=n;
            if(used>8192)throw new IOException("Unexpected local server response.");string text=new string(buffer,0,used);
            Dictionary<string,object> data=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(text);
            if(data==null||!data.ContainsKey("service")||!data.ContainsKey("instance")||!data.ContainsKey("port")||!data.ContainsKey("pid")||!data.ContainsKey("certificate_sha256")||
               Convert.ToString(data["service"])!="DS2-THQ-Portable-1.0"||Convert.ToString(data["instance"])!=GameLocator.Instance||Convert.ToInt32(data["port"])!=port)
                throw new IOException("Port is used by another program or another copy of this mod. Close that server using its Stop command. / Порт занят другой программой или копией мода.");
            string cert=Path.Combine(GameLocator.DataRoot,"local-cert.pem");
            if(verifyCertificate&&(!File.Exists(cert)||GameLocator.Hash(File.ReadAllBytes(cert))!=Convert.ToString(data["certificate_sha256"])))throw new IOException("Server certificate does not match this mod folder. Stop and restart the server.");
            return data;
        }
    }
    private static void EnsureServer()
    {
        if(Health()!=null)return;
        if(!File.Exists(Python)||!File.Exists(ServerFile))throw new FileNotFoundException("Extract the whole archive, including bin/runtime. / Распакуйте весь архив, включая runtime.");
        ProcessStartInfo start=new ProcessStartInfo(Python,"-B "+GameLocator.Quote(ServerFile)+" --ports "+port);
        start.UseShellExecute=false;start.CreateNoWindow=true;start.WindowStyle=ProcessWindowStyle.Hidden;start.WorkingDirectory=GameLocator.ModRoot;
        using(Process child=Process.Start(start))
        {
            try{for(int attempt=0;attempt<40;attempt++){if(child.HasExited)throw new IOException("Server exited. See bin/data/server-error.log.");if(Health()!=null)return;Thread.Sleep(200);}throw new IOException("Server start timed out.");}
            catch{if(!child.HasExited)child.Kill();throw;}
        }
    }
    private static void StopServer()
    {
        Dictionary<string,object> health=Health(false);if(health==null)return;
        int id=Convert.ToInt32(health["pid"]);bool verified=false;
        using(ManagementObjectSearcher search=new ManagementObjectSearcher("SELECT ExecutablePath,CommandLine FROM Win32_Process WHERE ProcessId="+id.ToString(CultureInfo.InvariantCulture)))
        using(ManagementObjectCollection rows=search.Get())foreach(ManagementObject row in rows)
        {
            string exe=Convert.ToString(row["ExecutablePath"]), command=Convert.ToString(row["CommandLine"]);
            verified=String.Equals(exe,Python,StringComparison.OrdinalIgnoreCase)&&command.Contains(GameLocator.Quote(ServerFile))&&command.Contains("--ports "+port);
        }
        if(!verified)throw new IOException("Server process identity mismatch; nothing stopped.");
        using(Process process=Process.GetProcessById(id)){process.Kill();if(!process.WaitForExit(5000))throw new IOException("Server did not stop.");}
    }
    private static int RunPython(string arguments)
    {
        ProcessStartInfo start=new ProcessStartInfo(Python,arguments);start.WorkingDirectory=GameLocator.ModRoot;start.UseShellExecute=false;start.CreateNoWindow=true;
        start.RedirectStandardError=true;start.RedirectStandardOutput=true;
        StringBuilder output=new StringBuilder();
        using(Process process=new Process())
        {
            process.StartInfo=start;
            DataReceivedEventHandler capture=delegate(object sender,DataReceivedEventArgs e){if(e.Data!=null)lock(output){if(output.Length<65536)output.AppendLine(e.Data);}};
            process.OutputDataReceived+=capture;process.ErrorDataReceived+=capture;
            process.Start();process.BeginOutputReadLine();process.BeginErrorReadLine();
            if(!process.WaitForExit(30000)){process.Kill();throw new IOException("Runtime check timed out.");}process.WaitForExit();
            Log(output.ToString());if(process.ExitCode!=0)throw new IOException("Python/tool failed. See bin/data/launcher.log.");return process.ExitCode;
        }
    }
    [STAThread]private static int Main(string[] args)
    {
        bool quiet=GameLocator.Has(args,"--quiet");
        try
        {
            Directory.CreateDirectory(GameLocator.DataRoot);
            string[] modes={"--server-only","--stop-server","--check","--choose-game","--nvidia60","--restore-fps","--offline","--verify-memory"};int selectedModes=0;
            foreach(string mode in modes)if(GameLocator.Has(args,mode))selectedModes++;
            if(selectedModes>1)throw new ArgumentException("Choose one operation at a time.");
            for(int i=0;i<args.Length;i++)
            {if(args[i]=="--game"||args[i]=="--port"){if(i+1>=args.Length||args[i+1].StartsWith("--"))throw new ArgumentException("Missing option value.");i++;}else if(args[i]!="--quiet"&&Array.IndexOf(modes,args[i])<0)throw new ArgumentException("Unknown option: "+args[i]);}
            // Verify that this portable folder is writable before starting anything.
            string test=Path.Combine(GameLocator.DataRoot,".write-"+Guid.NewGuid().ToString("N"));File.WriteAllText(test,"");File.Delete(test);
            string portValue=GameLocator.Option(args,"--port");if(portValue!=null&&(!Int32.TryParse(portValue,out port)||port<1024||port>65535))throw new ArgumentException("Invalid --port.");
            string message;
            using(Mutex single=new Mutex(false,"Local\\DS2-THQ-Portable-Launcher"))
            {
                bool held=false;try{try{held=single.WaitOne(0);}catch(AbandonedMutexException){held=true;}if(!held)throw new IOException("Another launcher is busy. Try again shortly.");
                    if(GameLocator.Has(args,"--server-only")){EnsureServer();message="Local server ready / Локальный сервер готов.";}
                    else if(GameLocator.Has(args,"--stop-server")){if(Process.GetProcessesByName("Darksiders2").Length!=0)throw new IOException("Exit the game normally before stopping the server. / Сначала закрой игру обычным способом.");StopServer();message="Server stopped. Mailbox kept / Сервер остановлен, почта сохранена.";}
                    else
                    {
                        string game=GameLocator.Resolve(args);
                        if(GameLocator.Has(args,"--check")){RunPython("-B -I -c "+GameLocator.Quote("import ssl,sqlite3,cryptography,cffi;ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)"));message="Game build and portable runtime verified. No game launched. / Игра и runtime проверены.";}
                        else if(GameLocator.Has(args,"--choose-game")){message="Game path saved / Путь к игре сохранён.";}
                        else if(GameLocator.Has(args,"--nvidia60")||GameLocator.Has(args,"--restore-fps"))
                        {RunPython("-B "+GameLocator.Quote(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,@"extras\nvidia_ds2.py"))+" "+(GameLocator.Has(args,"--nvidia60")?"apply":"restore")+" --game "+GameLocator.Quote(game));message="NVIDIA operation completed. See data/launcher.log / Настройки NVIDIA обработаны.";}
                        else
                        {
                            if(Process.GetProcessesByName("Darksiders2").Length!=0)throw new IOException("Exit Darksiders II normally first / Сначала закрой игру.");
                            if(GameLocator.Has(args,"--offline")){Process.Start(new ProcessStartInfo(Path.Combine(GameLocator.ModRoot,"DS2-Offline.exe"),"--game "+GameLocator.Quote(game)){UseShellExecute=false,WorkingDirectory=Path.GetDirectoryName(game)});return 0;}
                            EnsureServer();NativeTrust.Launch(game,port,GameLocator.Has(args,"--verify-memory"));
                            if(!GameLocator.Has(args,"--verify-memory"))return 0;
                            message="Certificate memory verification passed; suspended test process closed. No gameplay started.";
                        }
                    }
                }finally{if(held)single.ReleaseMutex();}
            }
            Log("OK "+message);if(!quiet)MessageBox.Show(message,"Darksiders II Local THQ 1.0",MessageBoxButtons.OK,MessageBoxIcon.Information);return 0;
        }
        catch(OperationCanceledException e){Log(e.Message);return 2;}
        catch(Exception e){Log("ERROR "+e);if(!quiet)MessageBox.Show(e.Message+"\n\nLogs / Журналы: bin/data","Darksiders II Local THQ 1.0",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;}
    }
}
