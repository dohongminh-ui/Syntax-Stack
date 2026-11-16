# Regenerates og-image.png, app icons and favicon.ico into frontend/. Needs Edge + network (Google Fonts).
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$edge = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$fe = (Resolve-Path (Join-Path $here '../../frontend')).Path
$src = $here -replace '\\', '/'

function Shot($url, $out, $w, $h, $extra) {
  & $edge --headless=new "--screenshot=$out" "--window-size=$w,$h" --hide-scrollbars --force-device-scale-factor=1 @extra $url | Out-Null
  Start-Sleep -Milliseconds 500
  $img = [System.Drawing.Image]::FromFile($out)
  if ($img.Width -ne $w -or $img.Height -ne $h) {   # crop to the exact size if the window came out different
    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.DrawImage($img, 0, 0, (New-Object System.Drawing.Rectangle 0, 0, $w, $h), [System.Drawing.GraphicsUnit]::Pixel)
    $g.Dispose(); $img.Dispose()
    $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
  } else { $img.Dispose() }
}

Shot "file:///$src/og-card.html" "$fe/og-image.png" 1200 630 @('--virtual-time-budget=4000')
Shot "file:///$src/icon.html?s=512" "$fe/icon-512.png" 512 512 @()
Shot "file:///$src/icon.html?s=512&mask=1" "$fe/icon-maskable-512.png" 512 512 @()
# small sizes: downscale the 512 render (headless Edge has a minimum window size)
function Scale($from, $to, $n) {
  $img = [System.Drawing.Image]::FromFile($from)
  $bmp = New-Object System.Drawing.Bitmap $n, $n
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.InterpolationMode = 'HighQualityBicubic'; $g.SmoothingMode = 'HighQuality'; $g.PixelOffsetMode = 'HighQuality'
  $g.DrawImage($img, 0, 0, $n, $n); $g.Dispose(); $img.Dispose()
  $bmp.Save($to, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
}
Scale "$fe/icon-512.png" "$fe/icon-192.png" 192
Scale "$fe/icon-512.png" "$fe/apple-touch-icon.png" 180
Scale "$fe/icon-512.png" "$fe/favicon-32.png" 32

# favicon.ico = ICO header + the 32px PNG
$png = [IO.File]::ReadAllBytes("$fe/favicon-32.png")
$ms = New-Object IO.MemoryStream; $bw = New-Object IO.BinaryWriter $ms
$bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]1)
$bw.Write([byte]32); $bw.Write([byte]32); $bw.Write([byte]0); $bw.Write([byte]0)
$bw.Write([uint16]1); $bw.Write([uint16]32); $bw.Write([uint32]$png.Length); $bw.Write([uint32]22)
$bw.Write($png); $bw.Flush()
[IO.File]::WriteAllBytes("$fe/favicon.ico", $ms.ToArray())
Remove-Item "$fe/favicon-32.png"
Write-Host 'done'
