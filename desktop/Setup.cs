using System;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Diagnostics;
using System.Windows.Forms;
class Setup {
  [STAThread] static void Main(string[] args) {
    Application.EnableVisualStyles();
    bool extractOnly = args.Length == 2 && args[0] == "--extract-only";
    bool testInstall = args.Length == 2 && args[0] == "--test-install";
    bool check = extractOnly || testInstall;
    string dest = check ? Path.GetFullPath(args[1]) : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "SnowbrickPrinter");
    if (!check && MessageBox.Show("Установить личное приложение печати Снегострой?\n\nКлючи подключаются отдельно после установки. Программа работает только при включённом компьютере.", "Снегострой — установка", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
    try {
      if (!check && Process.GetProcessesByName("SnowbrickPrinter").Length > 0) throw new Exception("Закройте Снегострой перед обновлением.");
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
      if (MessageBox.Show("Установка завершена. Открыть приложение?", "Снегострой", MessageBoxButtons.YesNo) == DialogResult.Yes) Process.Start(exe);
    } catch (Exception e) { if (check) Environment.Exit(1); else MessageBox.Show(e.Message,"Не удалось установить",MessageBoxButtons.OK,MessageBoxIcon.Error); }
  }
}
