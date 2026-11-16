$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    while ($null -ne ($line = [Console]::ReadLine())) {
        try {
            $request = $line | ConvertFrom-Json
            if ($request.operation -eq 'voices') {
                $names = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name })
                @{ voices = $names } | ConvertTo-Json -Compress
                continue
            }
            if ($request.voice) { $synth.SelectVoice([string]$request.voice) }
            else { $synth.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet, [System.Speech.Synthesis.VoiceAge]::NotSet, 0, [Globalization.CultureInfo]::GetCultureInfo('zh-CN')) }
            $synth.Rate = [int]$request.rate
            $synth.Volume = [int]$request.volume
            $memory = [System.IO.MemoryStream]::new()
            try {
                $synth.SetOutputToWaveStream($memory)
                $synth.Speak([string]$request.text)
                @{ audioBase64 = [Convert]::ToBase64String($memory.ToArray()) } | ConvertTo-Json -Compress
            } finally { $synth.SetOutputToNull(); $memory.Dispose() }
        } catch { @{ error = 'local-synthesis-failed' } | ConvertTo-Json -Compress }
    }
} finally { $synth.Dispose() }
