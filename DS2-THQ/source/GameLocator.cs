using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class GameLocator
{
    internal const string ExpectedHash="39FED14186C343FDF7F7D87B6FA779247A715347084D9E14A2708A0D7BF951B9";
    internal static string ModRoot { get { string baseDir=AppDomain.CurrentDomain.BaseDirectory; return File.Exists(Path.Combine(baseDir,"server.py")) ? baseDir.TrimEnd(Path.DirectorySeparatorChar) : Path.Combine(baseDir,"bin"); } }
    internal static string DataRoot { get { return Path.Combine(ModRoot,"data"); } }
    internal static string Hash(byte[] b){using(SHA256 h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(b)).Replace("-","").ToLowerInvariant();}
    internal static string HashFile(string p){using(SHA256 h=SHA256.Create())using(FileStream f=File.OpenRead(p))return BitConverter.ToString(h.ComputeHash(f)).Replace("-","").ToUpperInvariant();}
    internal static string Instance {get{return Hash(Encoding.UTF8.GetBytes(Path.GetFullPath(ModRoot).TrimEnd('\\').ToLowerInvariant()));}}
    internal static string Option(string[] args,string key){for(int i=0;i<args.Length;i++)if(args[i]==key){if(i+1>=args.Length||args[i+1].StartsWith("--"))throw new ArgumentException("Missing value for "+key);return args[i+1];}return null;}
    internal static bool Has(string[] args,string key){return Array.IndexOf(args,key)>=0;}
    internal static string Validate(string path)
    {
        path=Path.GetFullPath(path);
        if(!String.Equals(Path.GetFileName(path),"Darksiders2.exe",StringComparison.OrdinalIgnoreCase)||!File.Exists(path))throw new IOException("Select the original Darksiders2.exe / Выберите оригинальный Darksiders2.exe.");
        if(HashFile(path)!=ExpectedHash)throw new IOException("Unsupported game build. Original Steam app 50650, mainline538065 is required. Deathinitive Edition is not supported. / Неподдерживаемая сборка игры.");
        return path;
    }
    internal static string VdfValue(string text,string key)
    {
        Match m=Regex.Match(text,"\""+Regex.Escape(key)+"\"\\s*\"((?:\\\\.|[^\"\\\\])*)\"",RegexOptions.IgnoreCase);
        return m.Success?m.Groups[1].Value.Replace("\\\\","\\").Replace("\\\"","\""):null;
    }
    private static void Add(HashSet<string> paths,string path){if(!String.IsNullOrWhiteSpace(path))try{paths.Add(Path.GetFullPath(path));}catch(ArgumentException){} }
    private static string Reg(string key,string name){try{return Registry.GetValue(key,name,null) as string;}catch(System.Security.SecurityException){return null;}}
    internal static IEnumerable<string> Candidates()
    {
        HashSet<string> games=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        Add(games,Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"Darksiders2.exe"));
        string installed=Reg(@"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 50650","InstallLocation");
        Add(games,installed==null?null:Path.Combine(installed,"Darksiders2.exe"));
        HashSet<string> libraries=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        Add(libraries,Reg(@"HKEY_CURRENT_USER\Software\Valve\Steam","SteamPath"));
        Add(libraries,Reg(@"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Valve\Steam","InstallPath"));
        Add(libraries,Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),"Steam"));
        foreach(string steam in new List<string>(libraries))
        {
            string vdf=Path.Combine(steam,@"steamapps\libraryfolders.vdf");
            if(!File.Exists(vdf))continue;
            try{foreach(Match m in Regex.Matches(File.ReadAllText(vdf),"\"path\"\\s*\"((?:\\\\.|[^\"\\\\])*)\"",RegexOptions.IgnoreCase))Add(libraries,m.Groups[1].Value.Replace("\\\\","\\"));}catch(IOException){}catch(UnauthorizedAccessException){}
        }
        foreach(string library in libraries)
        {
            string manifest=Path.Combine(library,@"steamapps\appmanifest_50650.acf");
            if(!File.Exists(manifest))continue;
            try{string dir=VdfValue(File.ReadAllText(manifest),"installdir");if(dir!=null)Add(games,Path.Combine(library,"steamapps","common",dir,"Darksiders2.exe"));}catch(IOException){}catch(UnauthorizedAccessException){}
        }
        return games;
    }
    internal static string Resolve(string[] args)
    {
        Directory.CreateDirectory(DataRoot);
        string config=Path.Combine(DataRoot,"game-path.txt");
        string requested=Option(args,"--game"), selected=null;
        if(requested!=null)selected=Validate(requested);
        if(selected==null&&!Has(args,"--choose-game")&&File.Exists(config))
            try{selected=Validate(File.ReadAllText(config).Trim());}catch(IOException){}catch(UnauthorizedAccessException){}catch(ArgumentException){}catch(NotSupportedException){}
        if(selected==null&&!Has(args,"--choose-game"))
        {
            List<string> found=new List<string>();
            foreach(string candidate in Candidates())try{found.Add(Validate(candidate));}catch(IOException){}catch(UnauthorizedAccessException){}
            if(found.Count==1)selected=found[0];
        }
        if(selected==null)
        {
            if(Has(args,"--quiet"))throw new IOException("Game not found. Use --game <full path to Darksiders2.exe>.");
            using(OpenFileDialog picker=new OpenFileDialog())
            {
                picker.Title="Select original Darksiders II / Выберите оригинальную Darksiders II";
                picker.Filter="Darksiders2.exe|Darksiders2.exe";picker.CheckFileExists=true;picker.Multiselect=false;
                if(picker.ShowDialog()!=DialogResult.OK)throw new OperationCanceledException("Game selection cancelled / Выбор игры отменён.");
                selected=Validate(picker.FileName);
            }
        }
        File.WriteAllText(config,selected,new UTF8Encoding(false));return selected;
    }
    internal static string Quote(string value)
    {
        StringBuilder b=new StringBuilder("\"");int slashes=0;
        foreach(char c in value){if(c=='\\'){slashes++;continue;}if(c=='"'){b.Append('\\',slashes*2+1);b.Append(c);}else{b.Append('\\',slashes);b.Append(c);}slashes=0;}
        b.Append('\\',slashes*2);return b.Append('"').ToString();
    }
}
