# Reads printed text from an image or a scanned PDF with Windows' built-in OCR (no install needed).
# Usage: powershell -File ocr.ps1 <path> [maxPages]   -> prints the text, pages separated by a form feed.
param([string]$Path, [int]$MaxPages = 80)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]

$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$asTaskAction = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
function Await($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
function AwaitAction($op) { $t = $asTaskAction.Invoke($null, @($op)); $t.Wait(-1) | Out-Null }

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) { Write-Error "Windows OCR is not available on this PC." }

function Read-Stream($stream) {
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    ($res.Lines | ForEach-Object { $_.Text }) -join "`n"
}

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path $Path).Path)) ([Windows.Storage.StorageFile])
if ($Path -match '\.pdf$') {
    $doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
    $n = [Math]::Min($doc.PageCount, $MaxPages)
    $pages = for ($i = 0; $i -lt $n; $i++) {
        $page = $doc.GetPage($i)
        $ms = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
        $opt = New-Object Windows.Data.Pdf.PdfPageRenderOptions
        $opt.DestinationWidth = [uint32][Math]::Min(2000, [Math]::Max(1200, $page.Size.Width * 2))   # big enough for small print
        AwaitAction ($page.RenderToStreamAsync($ms, $opt))
        Read-Stream $ms
        [Console]::Error.WriteLine("page $($i + 1)/$n")
    }
    $pages -join "`f"
} else {
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    Read-Stream $stream
}
