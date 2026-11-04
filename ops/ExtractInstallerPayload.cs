using System;
using System.IO;
using System.Reflection;
class ExtractInstallerPayload {
  static void Main(string[] args) {
    using (var source=Assembly.LoadFrom(args[0]).GetManifestResourceStream("payload.zip"))
    using (var output=File.Create(args[1])) { source.CopyTo(output); }
  }
}
