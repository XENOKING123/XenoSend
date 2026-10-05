param(
  [string]$Exe,
  [string]$Out,
  [string]$Lang = "en",
  [string]$Theme = "midnight",
  [int]$Wait = 9,
  [string]$Title = "PS5 Send PKG / Payload",
  [string]$ExeArgs = "",
  [string]$WorkDir = ""
)
# Launch a frozen build, wait for its window, capture it, then stop it.
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string cls, string title);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
"@
[void][Win]::SetProcessDPIAware()
$env:SENDPP_FORCE_LANG = $Lang
$env:SENDPP_FORCE_THEME = $Theme
$env:KCFG_GRAPHICS_POSITION = "custom"
$env:KCFG_GRAPHICS_LEFT = "60"
$env:KCFG_GRAPHICS_TOP = "40"
if ($WorkDir) { Set-Location $WorkDir }
$sp = @{ FilePath = $Exe; PassThru = $true }
if ($ExeArgs) { $sp.ArgumentList = $ExeArgs }
if ($WorkDir) { $sp.WorkingDirectory = $WorkDir }
$p = Start-Process @sp
$h = [IntPtr]::Zero
for ($i = 0; $i -lt $Wait * 2 -and $h -eq [IntPtr]::Zero; $i++) { Start-Sleep -Milliseconds 500; $h = [Win]::FindWindow([NullString]::Value, $Title) }
if ($h -eq [IntPtr]::Zero) { "NO_WINDOW"; & taskkill /PID $p.Id /T /F | Out-Null; exit 2 }
Start-Sleep -Seconds 4   # let the first frames and remote checks settle
$r = New-Object Win+RECT
[void][Win]::GetWindowRect($h, [ref]$r)
$w = $r.Right - $r.Left; $ht = $r.Bottom - $r.Top
$bmp = New-Object System.Drawing.Bitmap $w, $ht
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"CAPTURED ${w}x${ht} -> $Out"
& taskkill /PID $p.Id /T /F | Out-Null   # whole tree: one-file builds run the app in a child process
