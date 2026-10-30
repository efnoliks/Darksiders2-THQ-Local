using System;
using System.IO;
internal static class TestLocator
{
    private static void Expect(bool condition,string label){if(!condition)throw new Exception(label);}
    private static int Main()
    {
        Expect(GameLocator.VdfValue("\"installdir\"   \"Darksiders 2\"","installdir")=="Darksiders 2","install dir");
        Expect(GameLocator.VdfValue("\"path\" \"D:\\\\Steam Library\\\\Игры\"","path")==@"D:\Steam Library\Игры","escaped VDF and Unicode");
        Expect(GameLocator.Quote(@"C:\folder with spaces\game.exe")=="\"C:\\folder with spaces\\game.exe\"","quote spaces");
        Expect(GameLocator.Quote("x\\")=="\"x\\\\\"","quote trailing slash");
        Expect(GameLocator.VdfValue("\"nothing\" \"value\"","path")==null,"missing value");
        bool rejected=false;try{GameLocator.Validate(Path.Combine(Path.GetTempPath(),"not-a-game.exe"));}catch(IOException){rejected=true;}Expect(rejected,"reject wrong executable");
        Console.WriteLine("Game locator, VDF, Unicode, argument quoting and rejection tests passed.");return 0;
    }
}
