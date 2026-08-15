$root = "C:\Users\Info\Desktop\SliqChat"
$logoFolder = Join-Path $root "static"
$logoFile = Join-Path $logoFolder "sliqchat-logo.png"

if (!(Test-Path $logoFolder)) {
    New-Item -ItemType Directory -Path $logoFolder | Out-Null
}

while ($true) {
    Clear-Host
    Write-Host "==================================" -ForegroundColor Cyan
    Write-Host "        SLIQCHAT LOGO MANAGER" -ForegroundColor Cyan
    Write-Host "==================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "1. PNG Logo auswählen"
    Write-Host "2. Logo-Ordner öffnen"
    Write-Host "3. Aktuelles Logo anzeigen"
    Write-Host "4. Beenden"
    Write-Host ""

    $choice = Read-Host "Auswahl"

    switch ($choice) {

        "1" {
            Add-Type -AssemblyName System.Windows.Forms

            $dialog = New-Object System.Windows.Forms.OpenFileDialog
            $dialog.Filter = "PNG Bilder (*.png)|*.png"
            $dialog.Title = "SliqChat Logo auswählen"

            if ($dialog.ShowDialog() -eq "OK") {

                Copy-Item $dialog.FileName $logoFile -Force

                Write-Host ""
                Write-Host "Logo erfolgreich gesetzt!" -ForegroundColor Green
                Write-Host "Gespeichert als:" -ForegroundColor Gray
                Write-Host $logoFile -ForegroundColor Yellow

                Start-Sleep -Seconds 2
            }
        }

        "2" {
            Start-Process explorer.exe $logoFolder
        }

        "3" {
            Clear-Host

            if (Test-Path $logoFile) {
                Write-Host "Aktuelles SliqChat Logo:" -ForegroundColor Green
                Write-Host $logoFile
                Write-Host ""
                Write-Host "Datei vorhanden: JA" -ForegroundColor Green
            }
            else {
                Write-Host "Noch kein Logo vorhanden." -ForegroundColor Yellow
            }

            Write-Host ""
            Pause
        }

        "4" {
            break
        }

        default {
            Write-Host ""
            Write-Host "Ungültige Auswahl." -ForegroundColor Red
            Start-Sleep -Seconds 1
        }
    }
}
