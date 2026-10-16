param(
  [Parameter(Mandatory=$true)][string]$ImagePath,
  [Parameter(Mandatory=$true)][double]$WidthMm,
  [Parameter(Mandatory=$true)][double]$HeightMm,
  [string]$PrinterName = '4BARCODE 3B-T361U'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$printer = Get-CimInstance Win32_Printer | Where-Object Name -EQ $PrinterName
if (-not $printer -or $printer.WorkOffline) { throw 'Выбранный принтер недоступен' }
$image = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $ImagePath).Path)
$document = [System.Drawing.Printing.PrintDocument]::new()
try {
  $document.PrinterSettings.PrinterName = $PrinterName
  if (-not $document.PrinterSettings.IsValid) { throw 'Не найден драйвер принтера' }
  $document.PrinterSettings.Copies = 1
  $document.DocumentName = 'CDEK - composition label'
  $document.PrintController = [System.Drawing.Printing.StandardPrintController]::new()
  $document.DefaultPageSettings.Margins = [System.Drawing.Printing.Margins]::new(0,0,0,0)
  $document.DefaultPageSettings.PaperSize = [System.Drawing.Printing.PaperSize]::new('CDEK', [int][Math]::Round($WidthMm/0.254), [int][Math]::Round($HeightMm/0.254))
  $document.DefaultPageSettings.Landscape = $false
  $document.add_PrintPage({
    param($sender, $event)
    $event.Graphics.PageUnit = [System.Drawing.GraphicsUnit]::Millimeter
    $event.Graphics.TranslateTransform(-$event.PageSettings.HardMarginX*0.254, -$event.PageSettings.HardMarginY*0.254)
    $event.Graphics.DrawImage($image, [System.Drawing.RectangleF]::new(0,0,[single]$WidthMm,[single]$HeightMm))
    $event.HasMorePages = $false
  })
  $document.Print()
  Write-Output 'PRINT_SUBMITTED'
} finally { $document.Dispose(); $image.Dispose() }
