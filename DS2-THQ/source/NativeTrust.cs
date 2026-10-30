// Runtime certificate-data changes only; original game instructions/files are untouched.
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Windows.Forms;

internal static class NativeTrust
{
    private const string ExpectedSha256 = "39FED14186C343FDF7F7D87B6FA779247A715347084D9E14A2708A0D7BF951B9";
    // One entry in the game's embedded CA certificate pointer array (.data).
    private static readonly IntPtr TrustPointer = new IntPtr(0x014e7c00);
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    private struct Startup
    {
        public int cb; public string reserved, desktop, title;
        public int x,y,xSize,ySize,xChars,yChars,fill,flags;
        public short show,reservedBytes; public IntPtr reserved2,input,output,error;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct ProcessInfo { public IntPtr process,thread; public uint pid,tid; }
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
    private static extern bool CreateProcess(string app, StringBuilder command,IntPtr pa,IntPtr ta,bool inherit,uint flags,IntPtr env,string cwd,ref Startup si,out ProcessInfo pi);
    [DllImport("kernel32.dll",SetLastError=true)]
    private static extern bool ReadProcessMemory(IntPtr p,IntPtr address,byte[] bytes,UIntPtr count,out UIntPtr read);
    [DllImport("kernel32.dll",SetLastError=true)]
    private static extern bool WriteProcessMemory(IntPtr p,IntPtr address,byte[] bytes,UIntPtr count,out UIntPtr written);
    [DllImport("kernel32.dll",SetLastError=true)]
    private static extern IntPtr VirtualAllocEx(IntPtr p,IntPtr address,UIntPtr count,uint kind,uint protection);
    [DllImport("kernel32.dll",SetLastError=true)]
    private static extern bool VirtualProtectEx(IntPtr p,IntPtr address,UIntPtr count,uint protection,out uint oldProtection);
    [DllImport("kernel32.dll")]private static extern uint ResumeThread(IntPtr t);
    [DllImport("kernel32.dll")]private static extern bool TerminateProcess(IntPtr p,uint code);
    [DllImport("kernel32.dll")]private static extern bool CloseHandle(IntPtr p);
    private static byte[] Read(IntPtr process,IntPtr address,int count)
    {
        byte[] b=new byte[count];UIntPtr n;
        if(!ReadProcessMemory(process,address,b,(UIntPtr)count,out n)||n.ToUInt64()!=(ulong)count)throw new IOException("Cannot verify client trust data.");
        return b;
    }
    private static void Write(IntPtr process,IntPtr address,byte[] b)
    {
        UIntPtr n;
        if(!WriteProcessMemory(process,address,b,(UIntPtr)b.Length,out n)||n.ToUInt64()!=(ulong)b.Length)throw new IOException("Cannot write client trust data.");
    }
    internal static void Launch(string exe,int port,bool verifyOnly)
    {
        ProcessInfo pi=new ProcessInfo();bool resumed=false;
        try
        {
            string actual;
            using(SHA256 hash=SHA256.Create())using(FileStream file=File.OpenRead(exe))actual=BitConverter.ToString(hash.ComputeHash(file)).Replace("-","");
            if(actual!=ExpectedSha256)throw new InvalidOperationException("Unsupported game EXE; no changes made.");
            string certPath=Path.Combine(GameLocator.DataRoot,"local-cert.pem");
            string pem=File.ReadAllText(certPath);
            if(!pem.StartsWith("-----BEGIN CERTIFICATE-----")||pem.Length>16384)throw new InvalidDataException("Invalid local certificate.");
            using(System.Net.Sockets.TcpClient check=new System.Net.Sockets.TcpClient("127.0.0.1",port)){}
            Environment.SetEnvironmentVariable("http_proxy","http://127.0.0.1:"+port+"");
            Environment.SetEnvironmentVariable("https_proxy","http://127.0.0.1:"+port+"");
            Environment.SetEnvironmentVariable("ALL_PROXY","http://127.0.0.1:"+port+"");
            Environment.SetEnvironmentVariable("NO_PROXY","");
            Environment.SetEnvironmentVariable("SteamAppId","50650");
            Environment.SetEnvironmentVariable("SteamGameId","50650");
            Startup si=new Startup();si.cb=Marshal.SizeOf(typeof(Startup));
            if(!CreateProcess(exe,new StringBuilder("\""+exe+"\""),IntPtr.Zero,IntPtr.Zero,false,4,IntPtr.Zero,Path.GetDirectoryName(exe),ref si,out pi))throw new IOException("Cannot start game: "+Marshal.GetLastWin32Error());
            byte[] before=Read(pi.process,TrustPointer,8);
            if(BitConverter.ToUInt32(before,0)!=0x012d8c20||BitConverter.ToUInt32(before,4)!=0x012d88b8)throw new InvalidOperationException("Unexpected trust-data layout; test launch stopped.");
            byte[] cert=Encoding.ASCII.GetBytes(pem+"\0");
            IntPtr memory=VirtualAllocEx(pi.process,IntPtr.Zero,(UIntPtr)cert.Length,0x3000,4);
            if(memory==IntPtr.Zero)throw new IOException("Cannot allocate the local certificate.");
            Write(pi.process,memory,cert);
            uint pointer=unchecked((uint)memory.ToInt32());Write(pi.process,TrustPointer,BitConverter.GetBytes(pointer));
            if(BitConverter.ToUInt32(Read(pi.process,TrustPointer,4),0)!=pointer)throw new IOException("Trust-data verification failed.");
            // GDS has a separate root PEM data buffer. Replace only that certificate,
            // after checking all original bytes against the hash-verified EXE.
            IntPtr gdsRoot=new IntPtr(0x013724d8);const int gdsLength=0x4e2;
            byte[] expected=new byte[gdsLength];
            using(FileStream original=File.OpenRead(exe)){original.Position=0xf712d8;if(original.Read(expected,0,gdsLength)!=gdsLength)throw new IOException("Cannot read original GDS certificate.");}
            byte[] existing=Read(pi.process,gdsRoot,gdsLength);
            for(int i=0;i<gdsLength;i++)if(existing[i]!=expected[i])throw new IOException("Unexpected GDS certificate data.");
            if(cert.Length>gdsLength)throw new IOException("Local certificate exceeds GDS buffer.");
            byte[] replacement=new byte[gdsLength];Array.Copy(cert,replacement,cert.Length);
            uint previous,ignored;
            if(!VirtualProtectEx(pi.process,gdsRoot,(UIntPtr)gdsLength,4,out previous))throw new IOException("Cannot write GDS certificate data.");
            try{Write(pi.process,gdsRoot,replacement);}
            finally{if(!VirtualProtectEx(pi.process,gdsRoot,(UIntPtr)gdsLength,previous,out ignored))throw new IOException("Cannot restore GDS data protection.");}
            byte[] verified=Read(pi.process,gdsRoot,gdsLength);
            for(int i=0;i<gdsLength;i++)if(verified[i]!=replacement[i])throw new IOException("GDS certificate verification failed.");
            if(verifyOnly)return;
            if(ResumeThread(pi.thread)==uint.MaxValue)throw new IOException("Cannot resume game.");
            resumed=true;
            try{File.WriteAllText(Path.Combine(GameLocator.DataRoot,"trust.log"),DateTime.UtcNow.ToString("o")+" PID="+pi.pid+"; THQ CA entry and GDS root certificate replaced in memory; original EXE file unchanged.\r\n");}catch(IOException){}catch(UnauthorizedAccessException){}
        }
        finally
        {
            if(pi.process!=IntPtr.Zero&&!resumed)TerminateProcess(pi.process,1);
            if(pi.thread!=IntPtr.Zero)CloseHandle(pi.thread);
            if(pi.process!=IntPtr.Zero)CloseHandle(pi.process);
        }
    }
}
