$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$outputDirectory = Join-Path $root 'deliverables'
$outputPath = Join-Path $outputDirectory 'ITMS_Professional_Review_II.pptx'
$previewDirectory = Join-Path $outputDirectory 'ITMS_Professional_Review_II_previews'
$networkImage = Join-Path $root 'itms\scenarios\networks\vijayawada\network_preview.png'
$corridorImage = Join-Path $root 'itms\web-app\public\landing\images\module-corridor.jpg'

New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $previewDirectory | Out-Null
if (Test-Path $outputPath) { Remove-Item -LiteralPath $outputPath -Force }

function OfficeRgb([int]$red, [int]$green, [int]$blue) {
    return [int]($red + (256 * $green) + (65536 * $blue))
}

function Points([double]$inches) {
    return [double]($inches * 72)
}

$C = @{
    Navy = OfficeRgb 11 31 61
    Ink = OfficeRgb 24 45 77
    Muted = OfficeRgb 93 111 138
    Blue = OfficeRgb 32 101 209
    Teal = OfficeRgb 0 166 153
    Sky = OfficeRgb 228 242 255
    Mint = OfficeRgb 224 248 243
    Gold = OfficeRgb 245 164 46
    Red = OfficeRgb 207 67 61
    Pale = OfficeRgb 246 249 253
    White = OfficeRgb 255 255 255
    Line = OfficeRgb 219 229 240
    Dark = OfficeRgb 7 23 45
}

$ppLayoutBlank = 12
$ppSlideSizeOnScreen16x9 = 15
$msoShapeRectangle = 1
$msoShapeRoundedRectangle = 5
$msoShapeOval = 9
$msoShapeRightArrow = 33
$msoFalse = 0
$msoTrue = -1
$msoBringToFront = 0
$ppSaveAsOpenXMLPresentation = 24

function Add-Box($slide, [int]$shapeType, [double]$left, [double]$top, [double]$width, [double]$height, [int]$fill, [int]$line = $fill, [double]$transparency = 0) {
    $shape = $slide.Shapes.AddShape($shapeType, (Points $left), (Points $top), (Points $width), (Points $height))
    $shape.Fill.ForeColor.RGB = $fill
    $shape.Fill.Transparency = $transparency
    $shape.Line.ForeColor.RGB = $line
    if ($line -eq $fill) { $shape.Line.Visible = $msoFalse }
    return $shape
}

function Add-Text($slide, [string]$text, [double]$left, [double]$top, [double]$width, [double]$height, [double]$size, [int]$color, [bool]$bold = $false, [string]$font = 'Aptos', [int]$alignment = 1) {
    $shape = $slide.Shapes.AddTextbox(1, (Points $left), (Points $top), (Points $width), (Points $height))
    $shape.TextFrame.WordWrap = $msoTrue
    $shape.TextFrame.MarginLeft = 0
    $shape.TextFrame.MarginRight = 0
    $shape.TextFrame.MarginTop = 0
    $shape.TextFrame.MarginBottom = 0
    $shape.TextFrame.AutoSize = 0
    $range = $shape.TextFrame.TextRange
    $range.Text = $text
    $range.Font.Name = $font
    $range.Font.Size = $size
    $range.Font.Color.RGB = $color
    $range.Font.Bold = $(if ($bold) { $msoTrue } else { $msoFalse })
    $range.ParagraphFormat.Alignment = $alignment
    return $shape
}

function Add-Line($slide, [double]$x1, [double]$y1, [double]$x2, [double]$y2, [int]$color, [double]$weight = 1.25) {
    $line = $slide.Shapes.AddLine((Points $x1), (Points $y1), (Points $x2), (Points $y2))
    $line.Line.ForeColor.RGB = $color
    $line.Line.Weight = $weight
    return $line
}

function Add-Image($slide, [string]$path, [double]$left, [double]$top, [double]$width, [double]$height) {
    $slide.Shapes.AddPicture($path, $msoFalse, $msoTrue, (Points $left), (Points $top), (Points $width), (Points $height)) | Out-Null
}

function Add-Label($slide, [string]$text, [double]$left, [double]$top, [double]$width, [int]$color = $C.Teal) {
    Add-Text $slide $text.ToUpper() $left $top $width 0.22 9.5 $color $true 'Aptos' 1 | Out-Null
}

function Add-Footer($slide, [int]$number, [string]$section = 'ITMS | PROFESSIONAL REVIEW II') {
    Add-Line $slide 0.55 7.14 12.78 7.14 $C.Line 0.75 | Out-Null
    Add-Text $slide $section 0.55 7.21 4.8 0.16 7.5 $C.Muted $false 'Aptos' 1 | Out-Null
    Add-Text $slide ('{0:00}' -f $number) 12.15 7.19 0.6 0.18 8 $C.Muted $true 'Aptos' 3 | Out-Null
}

function Add-Title($slide, [string]$eyebrow, [string]$title, [string]$subtitle = '') {
    Add-Label $slide $eyebrow 0.62 0.45 3.5
    Add-Text $slide $title 0.62 0.77 11.5 0.58 25 $C.Navy $true 'Aptos Display' 1 | Out-Null
    if ($subtitle) { Add-Text $slide $subtitle 0.63 1.43 11.25 0.38 11.5 $C.Muted $false 'Aptos' 1 | Out-Null }
    Add-Box $slide $msoShapeRectangle 0.62 1.96 0.55 0.04 $C.Teal | Out-Null
}

function Add-Card($slide, [double]$left, [double]$top, [double]$width, [double]$height, [string]$title, [string]$body, [int]$accent = $C.Blue, [string]$number = '') {
    Add-Box $slide $msoShapeRoundedRectangle $left $top $width $height $C.White $C.Line | Out-Null
    Add-Box $slide $msoShapeRoundedRectangle ($left + 0.18) ($top + 0.18) 0.1 ($height - 0.36) $accent $accent | Out-Null
    if ($number) { Add-Text $slide $number ($left + 0.42) ($top + 0.22) 0.45 0.2 9 $accent $true 'Aptos' 1 | Out-Null }
    $titleLeft = if ($number) { $left + 0.9 } else { $left + 0.42 }
    Add-Text $slide $title $titleLeft ($top + 0.22) ($width - ($titleLeft - $left) - 0.25) 0.33 13.2 $C.Ink $true 'Aptos' 1 | Out-Null
    Add-Text $slide $body ($left + 0.42) ($top + 0.68) ($width - 0.68) ($height - 0.86) 9.5 $C.Muted $false 'Aptos' 1 | Out-Null
}

function Add-Metric($slide, [double]$left, [double]$top, [double]$width, [double]$height, [string]$value, [string]$label, [string]$detail, [int]$accent = $C.Teal) {
    Add-Box $slide $msoShapeRoundedRectangle $left $top $width $height $C.Pale $C.Pale | Out-Null
    Add-Box $slide $msoShapeRoundedRectangle ($left + 0.18) ($top + 0.18) 0.12 ($height - 0.36) $accent $accent | Out-Null
    Add-Text $slide $value ($left + 0.45) ($top + 0.2) ($width - 0.6) 0.36 21 $C.Navy $true 'Aptos Display' 1 | Out-Null
    Add-Text $slide $label ($left + 0.45) ($top + 0.68) ($width - 0.6) 0.22 9.5 $C.Ink $true 'Aptos' 1 | Out-Null
    Add-Text $slide $detail ($left + 0.45) ($top + 0.99) ($width - 0.58) 0.32 8.2 $C.Muted $false 'Aptos' 1 | Out-Null
}

function Add-Stage($slide, [double]$left, [double]$top, [double]$width, [string]$step, [string]$title, [string]$caption, [int]$color) {
    Add-Box $slide $msoShapeRoundedRectangle $left $top $width 1.02 $C.White $C.Line | Out-Null
    Add-Box $slide $msoShapeOval ($left + 0.18) ($top + 0.19) 0.48 0.48 $color $color | Out-Null
    Add-Text $slide $step ($left + 0.18) ($top + 0.31) 0.48 0.14 8 $C.White $true 'Aptos' 2 | Out-Null
    Add-Text $slide $title ($left + 0.82) ($top + 0.2) ($width - 0.96) 0.22 11 $C.Ink $true 'Aptos' 1 | Out-Null
    Add-Text $slide $caption ($left + 0.82) ($top + 0.51) ($width - 0.96) 0.3 8.3 $C.Muted $false 'Aptos' 1 | Out-Null
}

$ppt = New-Object -ComObject PowerPoint.Application
$ppt.Visible = $msoTrue
$presentation = $ppt.Presentations.Add()
$presentation.PageSetup.SlideWidth = Points 13.333
$presentation.PageSetup.SlideHeight = Points 7.5

# 1 — Cover
$slide = $presentation.Slides.Add(1, $ppLayoutBlank)
Add-Box $slide $msoShapeRectangle 0 0 13.333 7.5 $C.Navy | Out-Null
Add-Box $slide $msoShapeOval 9.6 -1.2 5.1 5.1 $C.Blue $C.Blue 0.4 | Out-Null
Add-Box $slide $msoShapeOval 10.65 2.05 3.4 3.4 $C.Teal $C.Teal 0.23 | Out-Null
Add-Box $slide $msoShapeOval 8.1 5.8 1.0 1.0 $C.Gold $C.Gold 0.12 | Out-Null
Add-Text $slide 'CAPSTONE | PROFESSIONAL REVIEW II' 0.68 0.58 5.2 0.25 11 $C.Teal $true 'Aptos' 1 | Out-Null
Add-Text $slide "Intelligent Traffic Management`nand Emergency Response Platform" 0.68 1.05 7.9 1.35 29 $C.White $true 'Aptos Display' 1 | Out-Null
Add-Text $slide 'A simulation-validated system for adaptive traffic control, incident awareness, and emergency priority on the Vijayawada corridor.' 0.7 2.75 6.9 0.75 13 $C.Sky $false 'Aptos' 1 | Out-Null
Add-Box $slide $msoShapeRoundedRectangle 0.7 4.12 2.15 0.48 $C.Teal $C.Teal | Out-Null
Add-Text $slide 'SUMO + TraCI' 0.7 4.26 2.15 0.16 9 $C.White $true 'Aptos' 2 | Out-Null
Add-Box $slide $msoShapeRoundedRectangle 3.0 4.12 2.28 0.48 $C.Blue $C.Blue | Out-Null
Add-Text $slide 'SAFE SIGNAL CONTROL' 3.0 4.26 2.28 0.16 8.3 $C.White $true 'Aptos' 2 | Out-Null
Add-Box $slide $msoShapeRoundedRectangle 5.43 4.12 2.15 0.48 $C.Gold $C.Gold | Out-Null
Add-Text $slide 'EMERGENCY ROUTING' 5.43 4.26 2.15 0.16 8.1 $C.Navy $true 'Aptos' 2 | Out-Null
Add-Text $slide "B. Prakash Raj | 23BCE9434     M. Venkat Komal | 23BCE9377`nD. Preethi Darahasa | 23BCE8318     K. Vivek | 23BCE9396" 0.7 5.36 7.7 0.58 10.2 $C.White $false 'Aptos' 1 | Out-Null
Add-Text $slide 'Guide  N. Purnachand     |     SCOPE     |     VIT-AP University' 0.7 6.2 7.8 0.25 10 $C.Sky $false 'Aptos' 1 | Out-Null
Add-Text $slide 'REVIEW II | 2026' 11.0 6.77 1.65 0.2 8.5 $C.Sky $true 'Aptos' 3 | Out-Null

# 2 — From Review I to today
$slide = $presentation.Slides.Add(2, $ppLayoutBlank)
Add-Title $slide 'Journey since Review I' 'From planned system to measurable working modules' 'The implementation now has a corridor model, guarded control logic, emergency coordination, a live operator layer, and a trainable anomaly pipeline.'
$milestones = @(
    @('M0-M1', 'Foundation and live corridor', 'Docker/event contracts and a real Vijayawada SUMO corridor', $C.Blue),
    @('M2', 'Safety kernel', 'Signal interlocks and adversarial verification', $C.Teal),
    @('M3-M5', 'Adaptive control', 'Benchmarks, A-CA-MP and cycle supervision', $C.Gold),
    @('M6', 'Anomaly pipeline', 'Graph detection, calibration and operator gate', $C.Blue),
    @('M7', 'Emergency response', 'Dispatch and green-corridor preemption', $C.Teal)
)
$x = 0.65
foreach ($item in $milestones) {
    Add-Box $slide $msoShapeRoundedRectangle $x 2.42 2.27 1.9 $C.White $C.Line | Out-Null
    Add-Box $slide $msoShapeRoundedRectangle ($x + 0.18) 2.63 0.72 0.28 $item[3] $item[3] | Out-Null
    Add-Text $slide $item[0] ($x + 0.18) 2.71 0.72 0.12 7.6 $C.White $true 'Aptos' 2 | Out-Null
    Add-Text $slide $item[1] ($x + 0.18) 3.08 1.86 0.38 11 $C.Ink $true 'Aptos' 1 | Out-Null
    Add-Text $slide $item[2] ($x + 0.18) 3.66 1.86 0.38 8.6 $C.Muted $false 'Aptos' 1 | Out-Null
    $x += 2.45
}
Add-Box $slide $msoShapeRoundedRectangle 0.65 5.18 12.05 1.06 $C.Mint $C.Mint | Out-Null
Add-Text $slide 'Review II evidence' 0.95 5.46 1.95 0.2 10 $C.Teal $true 'Aptos' 1 | Out-Null
Add-Text $slide 'We report measured gains where they are proven, and explicitly state the remaining M6 model-accuracy and live-integration gaps.' 3.0 5.38 8.9 0.4 12.2 $C.Ink $true 'Aptos' 1 | Out-Null
Add-Footer $slide 2

# 3 — Problem and response
$slide = $presentation.Slides.Add(3, $ppLayoutBlank)
Add-Title $slide 'Context' 'Why one connected response is needed' 'Fixed plans, late reporting, and isolated emergency handling create avoidable delay and risk.'
Add-Card $slide 0.68 2.36 2.85 1.42 'Fixed timers' 'Pre-set schedules cannot react to changing queues, demand, or blocked lanes.' $C.Red '01'
Add-Card $slide 3.72 2.36 2.85 1.42 'Late incident awareness' 'A road blockage can propagate congestion before operators have reliable evidence.' $C.Gold '02'
Add-Card $slide 6.76 2.36 2.85 1.42 'Emergency delay' 'Ambulances still face the same signal sequence as general traffic.' $C.Blue '03'
Add-Card $slide 9.8 2.36 2.85 1.42 'Fragmented control' 'Optimisation, incident handling, and priority are often separate systems.' $C.Teal '04'
Add-Box $slide $msoShapeRoundedRectangle 0.68 4.43 12 1.34 $C.Navy $C.Navy | Out-Null
Add-Text $slide 'Our response' 0.98 4.75 1.45 0.18 10.3 $C.Teal $true 'Aptos' 1 | Out-Null
Add-Text $slide 'Sense traffic state  ->  decide safely  ->  coordinate emergency movement  ->  preserve an audit trail' 2.65 4.64 8.95 0.42 16.2 $C.White $true 'Aptos Display' 2 | Out-Null
Add-Text $slide 'The controller is deliberately constrained: every signal request is validated by a safety boundary before it can reach the simulator.' 2.65 5.16 8.95 0.24 9.5 $C.Sky $false 'Aptos' 2 | Out-Null
Add-Footer $slide 3

# 4 — Architecture
$slide = $presentation.Slides.Add(4, $ppLayoutBlank)
Add-Title $slide 'Architecture' 'A closed-loop system with safety at the command boundary' 'One event vocabulary lets SUMO, operators, and future roadside sources feed the same decision flow.'
Add-Stage $slide 0.67 2.43 2.55 '01' 'SENSE' 'SUMO / vehicle positions / operator input' $C.Blue
Add-Stage $slide 3.15 2.43 2.55 '02' 'ANALYSE' 'Traffic state + graph anomaly scores' $C.Teal
Add-Stage $slide 5.63 2.43 2.55 '03' 'DECIDE' 'Adaptive signals / route / corridor plan' $C.Gold
Add-Stage $slide 8.11 2.43 2.55 '04' 'ARBITRATE' 'Interlocks, priorities, audit and fallback' $C.Red
Add-Stage $slide 10.59 2.43 2.08 '05' 'ACT' 'TraCI signal commands and dashboard events' $C.Blue
foreach ($arrowX in @(2.86, 5.34, 7.82, 10.3)) { Add-Text $slide '->' $arrowX 2.79 0.22 0.25 18 $C.Muted $true 'Aptos' 2 | Out-Null; }
Add-Box $slide $msoShapeRoundedRectangle 1.35 4.35 10.55 1.12 $C.Pale $C.Line | Out-Null
Add-Text $slide 'COMMON EVENT CONTRACT' 1.72 4.64 2.02 0.18 9.6 $C.Blue $true 'Aptos' 1 | Out-Null
Add-Line $slide 4.0 4.6 4.0 5.18 $C.Line 1 | Out-Null
Add-Text $slide 'Vehicle positions | signal changes | incident candidate / confirmed / cleared | emergency commands' 4.3 4.55 6.96 0.44 11.2 $C.Ink $true 'Aptos' 1 | Out-Null
Add-Text $slide 'Phase 1 uses Redis Streams; service boundaries and contracts are designed for an eventual Kafka-backed deployment.' 4.3 5.04 6.96 0.2 8.7 $C.Muted $false 'Aptos' 1 | Out-Null
Add-Footer $slide 4

# 5 — Corridor
$slide = $presentation.Slides.Add(5, $ppLayoutBlank)
Add-Title $slide 'Simulation testbed' 'The Vijayawada MG Road corridor is the shared evaluation ground' 'The same seven-signal model underpins controller, incident, and emergency-response experiments.'
Add-Box $slide $msoShapeRoundedRectangle 0.65 2.25 7.55 3.95 $C.White $C.Line | Out-Null
Add-Image $slide $networkImage 0.83 2.45 7.18 3.42
Add-Metric $slide 8.63 2.35 1.88 1.26 '7' 'signalized junctions' 'plus 9 priority junctions' $C.Blue
Add-Metric $slide 10.72 2.35 1.88 1.26 '73' 'controlled links' 'used by M6 graph features' $C.Teal
Add-Metric $slide 8.63 3.86 1.88 1.26 '103' 'medical facilities' 'available to dispatch routing' $C.Gold
Add-Metric $slide 10.72 3.86 1.88 1.26 '1 Hz' 'live map updates' 'SUMO state published to UI' $C.Blue
Add-Box $slide $msoShapeRoundedRectangle 8.63 5.41 3.97 0.72 $C.Mint $C.Mint | Out-Null
Add-Text $slide 'Evaluation principle: hold the demand and random seeds constant while comparing the controller arms.' 8.88 5.62 3.43 0.25 8.8 $C.Ink $true 'Aptos' 1 | Out-Null
Add-Footer $slide 5

# 6 — Adaptive control
$slide = $presentation.Slides.Add(6, $ppLayoutBlank)
Add-Title $slide 'M5 | Adaptive traffic control' 'A-CA-MP makes local pressure decisions inside a safe cycle envelope' 'The controller remains adaptive; the supervisor ensures each demanded phase is served before the bounded cycle closes.'
Add-Box $slide $msoShapeRoundedRectangle 0.67 2.26 4.25 3.75 $C.Navy $C.Navy | Out-Null
Add-Text $slide 'CONTROL LOGIC' 1.0 2.64 1.9 0.18 9.5 $C.Teal $true 'Aptos' 1 | Out-Null
Add-Text $slide "Observe`nqueues and pressure" 1.0 3.03 2.3 0.54 17 $C.White $true 'Aptos Display' 1 | Out-Null
Add-Text $slide 'v' 2.78 3.72 0.25 0.25 18 $C.Teal $true 'Aptos' 2 | Out-Null
Add-Text $slide "Select highest-pressure`nvalid phase" 1.0 4.0 2.8 0.48 14.5 $C.White $true 'Aptos' 1 | Out-Null
Add-Text $slide 'v' 2.78 4.63 0.25 0.25 18 $C.Teal $true 'Aptos' 2 | Out-Null
Add-Text $slide 'Arbiter enforces minimum green, clearance, conflict lockout and maximum wait.' 1.0 4.98 3.3 0.56 10 $C.Sky $false 'Aptos' 1 | Out-Null
Add-Metric $slide 5.35 2.36 2.12 1.37 '-19.9%' 'light-demand delay' 'vs tuned Webster | 10/10 held-out seeds' $C.Teal
Add-Metric $slide 7.75 2.36 2.12 1.37 '-11.4%' 'medium-demand delay' 'vs tuned Webster | significant gate result' $C.Blue
Add-Metric $slide 10.15 2.36 2.12 1.37 '-11.6%' 'heavy-demand delay' 'vs tuned Webster | zero violations' $C.Gold
Add-Box $slide $msoShapeRoundedRectangle 5.35 4.04 6.93 1.47 $C.Pale $C.Line | Out-Null
Add-Text $slide 'Why the supervisor matters' 5.68 4.34 2.38 0.2 11 $C.Ink $true 'Aptos' 1 | Out-Null
Add-Text $slide 'It activates in only 0.6-1.0% of phase changes, yet removes the heavy-demand interlock violations seen with the ceiling alone.' 5.68 4.75 5.95 0.45 11.2 $C.Muted $false 'Aptos' 1 | Out-Null
Add-Footer $slide 6

# 7 — Anomaly detection
$slide = $presentation.Slides.Add(7, $ppLayoutBlank)
Add-Title $slide 'M6 | Incident awareness' 'The detection pipeline is built end to end; model accuracy is the current gap' 'We separate implementation completeness from validation completeness and report the proof-of-training metrics honestly.'
Add-Stage $slide 0.7 2.38 2.4 '01' 'FEATURES' '73 links x 10 traffic features per tick' $C.Blue
Add-Stage $slide 3.14 2.38 2.4 '02' 'GRAPH MODEL' 'Temporal graph autoencoder scores unusual links' $C.Teal
Add-Stage $slide 5.58 2.38 2.4 '03' 'CALIBRATE' 'Conformal threshold + persistence and cooldown' $C.Gold
Add-Stage $slide 8.02 2.38 2.4 '04' 'HUMAN GATE' 'Operator confirms or rejects a candidate' $C.Red
Add-Stage $slide 10.46 2.38 2.15 '05' 'AUDIT' 'State machine and hash-chained history' $C.Blue
Add-Box $slide $msoShapeRoundedRectangle 0.7 4.24 12 1.55 $C.Pale $C.Line | Out-Null
Add-Text $slide 'PROOF-OF-TRAINING RESULT' 1.0 4.55 2.35 0.18 9.5 $C.Red $true 'Aptos' 1 | Out-Null
Add-Text $slide 'Recall' 3.7 4.48 0.7 0.18 9.5 $C.Muted $true 'Aptos' 1 | Out-Null
Add-Text $slide '0.50' 3.7 4.77 0.8 0.35 23 $C.Navy $true 'Aptos Display' 1 | Out-Null
Add-Text $slide 'target >= 0.90' 3.7 5.2 1.15 0.16 8.3 $C.Red $false 'Aptos' 1 | Out-Null
Add-Text $slide 'Latency' 5.55 4.48 0.8 0.18 9.5 $C.Muted $true 'Aptos' 1 | Out-Null
Add-Text $slide '40 s' 5.55 4.77 1.0 0.35 23 $C.Navy $true 'Aptos Display' 1 | Out-Null
Add-Text $slide 'target < 30 s' 5.55 5.2 1.15 0.16 8.3 $C.Red $false 'Aptos' 1 | Out-Null
Add-Text $slide 'Status' 7.4 4.48 0.8 0.18 9.5 $C.Muted $true 'Aptos' 1 | Out-Null
Add-Text $slide '105+' 7.4 4.77 1.2 0.35 23 $C.Navy $true 'Aptos Display' 1 | Out-Null
Add-Text $slide 'dedicated automated tests' 7.4 5.2 1.6 0.16 8.3 $C.Teal $false 'Aptos' 1 | Out-Null
Add-Text $slide 'Next evidence' 9.45 4.48 1.0 0.18 9.5 $C.Muted $true 'Aptos' 1 | Out-Null
Add-Text $slide '30 runs' 9.45 4.77 1.5 0.35 23 $C.Navy $true 'Aptos Display' 1 | Out-Null
Add-Text $slide 'record normal traffic; train 50-80 epochs' 9.45 5.2 2.4 0.25 8.3 $C.Teal $false 'Aptos' 1 | Out-Null
Add-Footer $slide 7

# 8 — Emergency corridor
$slide = $presentation.Slides.Add(8, $ppLayoutBlank)
Add-Title $slide 'M7 | Emergency response' 'Dispatch and green-corridor coordination reduce emergency delay' 'Instead of each signal reacting in isolation, the route is reserved and released as the vehicle passes.'
Add-Box $slide $msoShapeRoundedRectangle 0.66 2.31 5.05 3.7 $C.White $C.Line | Out-Null
Add-Image $slide $corridorImage 0.85 2.5 4.67 3.32
Add-Metric $slide 6.13 2.38 1.92 1.28 '3.5-4.3' 'EV time saved' '% reduction vs reactive preemption' $C.Teal
Add-Metric $slide 8.35 2.38 1.92 1.28 '25-31' 'less time lost' '% reduction vs reactive preemption' $C.Blue
Add-Metric $slide 10.57 2.38 1.92 1.28 '31-46' 'fewer EV stops' '% reduction; statistically significant' $C.Gold
Add-Box $slide $msoShapeRoundedRectangle 6.13 4.03 6.36 1.5 $C.Mint $C.Mint | Out-Null
Add-Text $slide 'Dispatch decision' 6.43 4.32 1.68 0.2 10.5 $C.Teal $true 'Aptos' 1 | Out-Null
Add-Text $slide 'Hospital destinations come from real map data; the router selects a clinically suitable destination using live traffic cost.' 6.43 4.72 5.55 0.42 11 $C.Ink $true 'Aptos' 1 | Out-Null
Add-Text $slide 'Measured with no meaningful cross-street traffic penalty.' 6.43 5.22 4.3 0.17 8.5 $C.Muted $false 'Aptos' 1 | Out-Null
Add-Footer $slide 8

# 9 — Live interface
$slide = $presentation.Slides.Add(9, $ppLayoutBlank)
Add-Title $slide 'Integration and demonstrable system' 'The live operator flow now drives the controlled simulation' 'The web app is not a mock-up: it receives live events, displays candidates, and can affect the running SUMO scenario.'
Add-Box $slide $msoShapeRoundedRectangle 0.72 2.38 11.92 3.67 $C.Navy $C.Navy | Out-Null
Add-Text $slide 'LIVE RUN' 1.12 2.74 1.15 0.18 10 $C.Teal $true 'Aptos' 1 | Out-Null
Add-Text $slide "SUMO corridor controlled by`nA-CA-MP" 1.12 3.15 2.75 0.55 18 $C.White $true 'Aptos Display' 1 | Out-Null
Add-Text $slide '->' 4.05 3.47 0.38 0.25 22 $C.Teal $true 'Aptos' 2 | Out-Null
Add-Text $slide "Redis event stream`nand API service" 4.55 3.15 2.32 0.55 18 $C.White $true 'Aptos Display' 1 | Out-Null
Add-Text $slide '->' 7.05 3.47 0.38 0.25 22 $C.Teal $true 'Aptos' 2 | Out-Null
Add-Text $slide "WebSocket operator`ndashboard" 7.55 3.15 2.48 0.55 18 $C.White $true 'Aptos Display' 1 | Out-Null
Add-Text $slide '->' 10.22 3.47 0.38 0.25 22 $C.Teal $true 'Aptos' 2 | Out-Null
Add-Text $slide "Approved`ncommand" 10.75 3.15 1.33 0.55 18 $C.White $true 'Aptos Display' 1 | Out-Null
Add-Line $slide 1.15 4.34 12.1 4.34 $C.Blue 1.2 | Out-Null
Add-Text $slide 'Current verified capabilities' 1.12 4.7 2.2 0.2 10 $C.Teal $true 'Aptos' 1 | Out-Null
Add-Text $slide 'Live vehicle/signal state at 1 Hz | Candidate confirmation/rejection API | Operator-driven anomaly injection | Dynamic emergency re-routing' 1.12 5.08 10.7 0.28 10.5 $C.Sky $false 'Aptos' 1 | Out-Null
Add-Text $slide 'Note: benchmarked M7 preemption is completed; wiring that engine into the live operator demo is an explicit remaining integration task.' 1.12 5.55 10.82 0.18 8.3 $C.Gold $false 'Aptos' 1 | Out-Null
Add-Footer $slide 9

# 10 — Validation
$slide = $presentation.Slides.Add(10, $ppLayoutBlank)
Add-Title $slide 'Validation discipline' 'Results are gated with safety checks, paired comparisons, and traceable artefacts' 'The project deliberately treats negative results and caveats as findings - not hidden exceptions.'
Add-Card $slide 0.68 2.34 3.73 1.5 'Safety first' 'Nine property tests each generate 10,000 adversarial cases. The safety kernel rejects unsafe timing plans before they reach SUMO.' $C.Red 'A'
Add-Card $slide 4.8 2.34 3.73 1.5 'Fair comparison' 'Controller arms share demand and random seeds. Results use paired held-out evaluation seeds and confidence intervals.' $C.Blue 'B'
Add-Card $slide 8.92 2.34 3.73 1.5 'Reproducible artefacts' 'Raw runs, scripts, event schemas, tests, and benchmark gates are preserved in the repository.' $C.Teal 'C'
Add-Box $slide $msoShapeRoundedRectangle 0.68 4.48 12 1.18 $C.Pale $C.Line | Out-Null
Add-Text $slide 'What we do not overclaim' 0.98 4.79 2.4 0.2 10.5 $C.Red $true 'Aptos' 1 | Out-Null
Add-Text $slide 'M6 graph detector is correctly wired but undertrained; the camera-based vision stream remains future scope; simulation demand and pedestrian behaviour are still simplified.' 3.58 4.68 8.47 0.43 11.2 $C.Ink $true 'Aptos' 1 | Out-Null
Add-Footer $slide 10

# 11 — Status and next steps
$slide = $presentation.Slides.Add(11, $ppLayoutBlank)
Add-Title $slide 'Status and next review plan' 'Build is strong where evidence exists; close the accuracy and integration gaps next' 'A review-ready project is one that makes its tested boundaries as clear as its achievements.'
$status = @(
    @('Validated now', 'M0-M5 foundations, safe adaptive control, M7 dispatch/corridor benchmarks', $C.Teal),
    @('Implemented, needs evidence', 'M6 graph-detection pipeline; expand normal-data collection and train the shipped model', $C.Gold),
    @('Next integration', 'Connect the benchmarked M7 corridor engine to the live operator workflow', $C.Blue),
    @('Future scope', 'Camera/YOLO evidence stream, calibrated field demand, pedestrian-aware signal phases', $C.Muted)
)
$top = 2.28
$counter = 1
foreach ($item in $status) {
    Add-Box $slide $msoShapeRoundedRectangle 0.72 $top 11.9 0.75 $C.White $C.Line | Out-Null
    Add-Box $slide $msoShapeOval 1.0 ($top + 0.16) 0.42 0.42 $item[2] $item[2] | Out-Null
    Add-Text $slide $counter 1.0 ($top + 0.29) 0.42 0.12 7.2 $C.White $true 'Aptos' 2 | Out-Null
    Add-Text $slide $item[0] 1.72 ($top + 0.17) 2.15 0.2 11.3 $C.Ink $true 'Aptos' 1 | Out-Null
    Add-Text $slide $item[1] 4.2 ($top + 0.17) 7.7 0.34 10 $C.Muted $false 'Aptos' 1 | Out-Null
    $top += 0.9
    $counter++
}
Add-Footer $slide 11

# 12 — Close
$slide = $presentation.Slides.Add(12, $ppLayoutBlank)
Add-Box $slide $msoShapeRectangle 0 0 13.333 7.5 $C.Navy | Out-Null
Add-Box $slide $msoShapeOval -1.5 4.8 4.0 4.0 $C.Teal $C.Teal 0.35 | Out-Null
Add-Box $slide $msoShapeOval 10.1 -1.0 4.2 4.2 $C.Blue $C.Blue 0.25 | Out-Null
Add-Text $slide 'Thank you' 0.7 1.24 6.2 0.6 29 $C.White $true 'Aptos Display' 1 | Out-Null
Add-Text $slide 'Questions and discussion' 0.7 1.98 5.5 0.3 15 $C.Teal $true 'Aptos' 1 | Out-Null
Add-Text $slide 'We are ready to demonstrate the corridor, explain the measurement gates, and discuss the M6 training plan.' 0.7 2.6 6.15 0.65 13 $C.Sky $false 'Aptos' 1 | Out-Null
Add-Line $slide 0.7 4.08 6.6 4.08 $C.Teal 1.2 | Out-Null
Add-Text $slide 'B. Prakash Raj | M. Venkat Komal | D. Preethi Darahasa | K. Vivek' 0.7 4.47 7.8 0.22 10.2 $C.White $true 'Aptos' 1 | Out-Null
Add-Text $slide 'Guide: N. Purnachand     |     SCOPE     |     VIT-AP University' 0.7 4.88 6.9 0.22 9.5 $C.Sky $false 'Aptos' 1 | Out-Null
Add-Text $slide 'ITMS | PROFESSIONAL REVIEW II' 10.2 6.66 2.45 0.18 8.7 $C.Sky $true 'Aptos' 3 | Out-Null

$presentation.SaveAs($outputPath, $ppSaveAsOpenXMLPresentation)
$presentation.Export($previewDirectory, 'PNG', 1600, 900)
$presentation.Close()
$ppt.Quit()
[Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) | Out-Null
[Runtime.InteropServices.Marshal]::ReleaseComObject($ppt) | Out-Null
[GC]::Collect()
[GC]::WaitForPendingFinalizers()
Write-Output "Created $outputPath"
