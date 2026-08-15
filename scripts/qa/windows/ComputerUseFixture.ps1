Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = "Birkin Computer Use QA Fixture"
$form.Width = 560
$form.Height = 420
$form.StartPosition = "Manual"
$form.Location = New-Object System.Drawing.Point(160, 160)

$heading = New-Object System.Windows.Forms.Label
$heading.Text = "Birkin Computer Use QA"
$heading.Location = New-Object System.Drawing.Point(24, 24)
$heading.AutoSize = $true
$heading.Font = New-Object System.Drawing.Font(
    "Segoe UI",
    18,
    [System.Drawing.FontStyle]::Bold
)
$form.Controls.Add($heading)

$value = New-Object System.Windows.Forms.TextBox
$value.Name = "FixtureValue"
$value.AccessibleName = "Synthetic value"
$value.Text = "before"
$value.Location = New-Object System.Drawing.Point(24, 80)
$value.Width = 360
$form.Controls.Add($value)

$counter = New-Object System.Windows.Forms.Label
$counter.Name = "FixtureCounter"
$counter.AccessibleName = "Synthetic counter"
$counter.Text = "count=0"
$counter.Location = New-Object System.Drawing.Point(24, 160)
$counter.AutoSize = $true
$form.Controls.Add($counter)

$button = New-Object System.Windows.Forms.Button
$button.Name = "FixtureIncrement"
$button.AccessibleName = "Increment synthetic counter"
$button.Text = "Increment synthetic counter"
$button.Location = New-Object System.Drawing.Point(24, 120)
$button.Width = 240
$button.Add_Click({
    $current = [int]($counter.Text.Replace("count=", ""))
    $next = $current + 1
    $counter.Text = "count=$next"
    $button.Text = "Increment synthetic counter ($next)"
})
$form.Controls.Add($button)

$list = New-Object System.Windows.Forms.ListBox
$list.Name = "FixtureRows"
$list.AccessibleName = "Synthetic rows"
$list.Location = New-Object System.Drawing.Point(24, 200)
$list.Width = 480
$list.Height = 140
1..30 | ForEach-Object { [void]$list.Items.Add("Synthetic row $_") }
$form.Controls.Add($list)

$form.Add_Shown({
    $form.Activate()
    [Console]::Out.WriteLine("READY $PID")
    [Console]::Out.Flush()
})

[System.Windows.Forms.Application]::Run($form)
