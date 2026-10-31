using System;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Diagnostics;
using System.Windows.Forms;
using System.Text;
using System.Security.Cryptography;
using System.Collections.Generic;
using System.Web.Script.Serialization;
class Setup {
  static void Provision(string home) {
    using (Stream key = Assembly.GetExecutingAssembly().GetManifestResourceStream("preconnected.token")) {
      if (key == null) return;
      string token;
      using (StreamReader reader = new StreamReader(key, Encoding.UTF8)) token = reader.ReadToEnd().Trim();
      if (!System.Text.RegularExpressions.Regex.IsMatch(token, "^[A-Za-z0-9_-]{32,128}$")) throw new Exception("Некорректный персональный комплект подключения.");
      Directory.CreateDirectory(home);
      byte[] plain = Encoding.UTF8.GetBytes(token);
      try { File.WriteAllBytes(Path.Combine(home,"device-key.bin"), ProtectedData.Protect(plain,null,DataProtectionScope.CurrentUser)); }
      finally { Array.Clear(plain,0,plain.Length); }
      string settings = Path.Combine(home,"settings.json");
      JavaScriptSerializer json = new JavaScriptSerializer();
      Dictionary<string,object> config = File.Exists(settings) ? json.Deserialize<Dictionary<string,object>>(File.ReadAllText(settings)) : new Dictionary<string,object>();
      config["paired"] = true;
      string temp = settings + ".install.tmp";
      File.WriteAllText(temp,json.Serialize(config),new UTF8Encoding(false));
      if (File.Exists(settings)) File.Replace(temp,settings,null); else File.Move(temp,settings);
    }
  }
  [STAThread] static void Main(string[] args) {
    Application.EnableVisualStyles();
    bool extractOnly = args.Length == 2 && args[0] == "--extract-only";
    bool testInstall = args.Length == 2 && args[0] == "--test-install";
    bool check = extractOnly || testInstall;
    string dest = check ? Path.GetFullPath(args[1]) : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "SnowbrickPrinter");
    bool personal = Assembly.GetExecutingAssembly().GetManifestResourceInfo("preconnected.token") != null;
    string connection = personal ? "Подключение к вашему аккаунту уже включено. Вход и код не нужны. После установки выберите принтеры в настройках." : "Ключи подключаются отдельно после установки.";
    if (!check && MessageBox.Show("Установить личное приложение печати Снегострой?\n\n"+connection+"\nПрограмма работает только при включённом компьютере.", "Снегострой — установка", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
    try {
      if (!check && Process.GetProcessesByName("SnowbrickPrinter").Length > 0) throw new Exception("Завершите модуль: Настройки → Общие настройки → Завершить модуль. Затем повторите обновление.");
      Directory.CreateDirectory(dest);
      using (Stream payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
      using (ZipArchive archive = new ZipArchive(payload, ZipArchiveMode.Read)) {
        foreach (ZipArchiveEntry entry in archive.Entries) {
          string path = Path.GetFullPath(Path.Combine(dest, entry.FullName));
          if (!path.StartsWith(dest.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new Exception("Некорректный архив установки.");
          if (entry.FullName.EndsWith("/")) { Directory.CreateDirectory(path); continue; }
          Directory.CreateDirectory(Path.GetDirectoryName(path));
          using (Stream source = entry.Open()) using (Stream output = File.Create(path)) source.CopyTo(output);
        }
      }
      if (extractOnly) return;
      Provision(testInstall ? Path.Combine(dest,"test-profile") : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SnowbrickPrinter"));
      string exe = Path.Combine(dest, "SnowbrickPrinter.exe");
      string menu = testInstall ? Path.Combine(dest,"test-shortcuts","StartMenu") : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "Снегострой");
      string desktop = testInstall ? Path.Combine(dest,"test-shortcuts","Desktop") : Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
      Directory.CreateDirectory(menu);
      Directory.CreateDirectory(desktop);
      Type type = Type.GetTypeFromProgID("WScript.Shell"); dynamic shell = Activator.CreateInstance(type);
      dynamic shortcut = shell.CreateShortcut(Path.Combine(menu, "Печать СДЭК.lnk"));
      shortcut.TargetPath = exe; shortcut.WorkingDirectory = dest; shortcut.Save();
      dynamic desktopShortcut = shell.CreateShortcut(Path.Combine(desktop, "Снегострой — печать этикеток.lnk"));
      desktopShortcut.TargetPath = exe; desktopShortcut.WorkingDirectory = dest; desktopShortcut.Description = "Заказы amoCRM и печать этикеток"; desktopShortcut.Save();
      File.WriteAllText(Path.Combine(dest,"Удаление.txt"), "Закройте приложение. Снимите автозапуск в приложении. Удалите эту папку, ярлык Снегострой с рабочего стола и из меню Пуск. История и ключ хранятся отдельно в %LOCALAPPDATA%\\SnowbrickPrinter. Доступ устройства можно отозвать на snowbrick.ru.");
      if (testInstall) return;
      using (var startup = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run")) {
        startup.SetValue("SnowbrickPrinter", "\""+exe+"\" --background-agent");
      }
      string settingsHome=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"SnowbrickPrinter");
      Directory.CreateDirectory(settingsHome);
      string configPath=Path.Combine(settingsHome,"settings.json");
      var serializer=new JavaScriptSerializer();
      var config=File.Exists(configPath)?serializer.Deserialize<Dictionary<string,object>>(File.ReadAllText(configPath)):new Dictionary<string,object>();
      config["startup"]=true;File.WriteAllText(configPath,serializer.Serialize(config),new UTF8Encoding(false));

      if (MessageBox.Show("Установка завершена. Открыть приложение?", "Снегострой", MessageBoxButtons.YesNo) == DialogResult.Yes) Process.Start(exe);
    } catch (Exception e) { if (check) Environment.Exit(1); else MessageBox.Show(e.Message,"Не удалось установить",MessageBoxButtons.OK,MessageBoxIcon.Error); }
  }
}
