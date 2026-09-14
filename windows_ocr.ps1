param(
    [Parameter(Mandatory=$true)]
    [string]$ImagePath
)

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
    [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null

    function Await-AsyncOp($asyncOp, [Type]$returnType) {
        $methods = [System.WindowsRuntimeSystemExtensions].GetMethods()
        $asTask = $methods | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 } | Select-Object -First 1
        $concrete = $asTask.MakeGenericMethod($returnType)
        $task = $concrete.Invoke($null, @($asyncOp))
        return $task.GetAwaiter().GetResult()
    }

    $fullPath = [System.IO.Path]::GetFullPath($ImagePath)
    if (-not (Test-Path $fullPath)) {
        Write-Output "[]"
        exit 0
    }

    $file = Await-AsyncOp ([Windows.Storage.StorageFile]::GetFileFromPathAsync($fullPath)) ([Windows.Storage.StorageFile])
    $stream = Await-AsyncOp ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await-AsyncOp ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $softBmp = Await-AsyncOp ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("es"))
    }
    if ($null -eq $engine) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("en-US"))
    }

    $ocrResult = Await-AsyncOp ($engine.RecognizeAsync($softBmp)) ([Windows.Media.Ocr.OcrResult])

    $items = @()
    foreach ($line in $ocrResult.Lines) {
        if ($line.Words.Count -eq 0) { continue }
        $minX = [double]::MaxValue
        $minY = [double]::MaxValue
        $maxX = [double]::MinValue
        $maxY = [double]::MinValue

        foreach ($word in $line.Words) {
            $r = $word.BoundingRect
            $wx = [double]$r.X
            $wy = [double]$r.Y
            $ww = [double]$r.Width
            $wh = [double]$r.Height

            if ($wx -lt $minX) { $minX = $wx }
            if ($wy -lt $minY) { $minY = $wy }
            if (($wx + $ww) -gt $maxX) { $maxX = ($wx + $ww) }
            if (($wy + $wh) -gt $maxY) { $maxY = ($wy + $wh) }

            $items += [PSCustomObject]@{
                type = "word"
                text = $word.Text
                x = [int][Math]::Round($wx)
                y = [int][Math]::Round($wy)
                w = [int][Math]::Round($ww)
                h = [int][Math]::Round($wh)
                cx = [int][Math]::Round($wx + ($ww / 2.0))
                cy = [int][Math]::Round($wy + ($wh / 2.0))
            }
        }

        # Add full line entry
        $lw = $maxX - $minX
        $lh = $maxY - $minY
        $items += [PSCustomObject]@{
            type = "line"
            text = $line.Text
            x = [int][Math]::Round($minX)
            y = [int][Math]::Round($minY)
            w = [int][Math]::Round($lw)
            h = [int][Math]::Round($lh)
            cx = [int][Math]::Round($minX + ($lw / 2.0))
            cy = [int][Math]::Round($minY + ($lh / 2.0))
        }
    }

    $json = $items | ConvertTo-Json -Compress
    Write-Output $json
}
catch {
    Write-Output "[]"
}
