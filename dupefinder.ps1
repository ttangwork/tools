# PowerShell script to find duplicate files based on checksum
param(
    [string]$Path = "C:\\Test",
    [switch]$DeleteDuplicates
)

# Function to compute file hash
function Get-FileHashSHA256 {
    param([string]$FilePath)
    try {
        return (Get-FileHash -Path $FilePath -Algorithm SHA256).Hash
    } catch {
        Write-Host "Error computing hash for: $FilePath" -ForegroundColor Red
        return $null
    }
}

# Function to format file size
function Format-FileSize {
    param([double]$SizeInBytes)
    if ($SizeInBytes -ge 1TB) {
        return "{0:N1} TB" -f ($SizeInBytes / 1TB)
    } elseif ($SizeInBytes -ge 1GB) {
        return "{0:N1} GB" -f ($SizeInBytes / 1GB)
    } elseif ($SizeInBytes -ge 1MB) {
        return "{0:N1} MB" -f ($SizeInBytes / 1MB)
    } elseif ($SizeInBytes -ge 1KB) {
        return "{0:N1} KB" -f ($SizeInBytes / 1KB)
    } else {
        return "{0} Bytes" -f $SizeInBytes
    }
}

# Store file hashes
$hashTable = @{}

# Get all files recursively
$files = Get-ChildItem -Path $Path -File -Recurse
$totalFiles = $files.Count
$counter = 0

# Initialize progress bar
Write-Host "Checking files for duplicates..."
foreach ($file in $files) {
    $counter++
    Write-Progress -Activity "Processing Files" -Status "Checking $counter of $totalFiles" -PercentComplete (($counter / $totalFiles) * 100)
    
    $hash = Get-FileHashSHA256 -FilePath $file.FullName
    
    if ($null -ne $hash) { # Ensure hash is not null
        if ($hashTable.ContainsKey($hash)) {
            # If hash exists, add to duplicates
            $hashTable[$hash] += @($file.FullName)
        } else {
            # Otherwise, store the hash
            $hashTable[$hash] = @($file.FullName)
        }
    } else {
        Write-Host "Skipping file due to hash computation failure: $($file.FullName)" -ForegroundColor Red
    }
}

# Identify and process duplicate files
$duplicateFiles = $hashTable.Values | Where-Object { $_.Count -gt 1 }
Write-Progress -Activity "Processing Files" -Completed

$totalDuplicateSize = 0

if ($duplicateFiles.Count -gt 0) {
    Write-Host "Duplicate files found:" -ForegroundColor Yellow
    $htmlContent = "<html><head><title>Duplicate Files Report</title>"
    $htmlContent += "<style>
        body { font-family: Arial, sans-serif; margin: 20px; padding: 20px; }
        h1 { color: #d9534f; }
        ul { list-style-type: none; padding: 0; }
        li { padding: 8px; border-bottom: 1px solid #ddd; }
        strong { color: #0275d8; }
        h2 { color: #5cb85c; }
    </style></head><body><h1>Duplicate Files Report</h1><ul>"
    
    foreach ($group in $duplicateFiles) {
        Write-Host "-------------------"
        $htmlContent += "<li><strong>Duplicate Group:</strong><ul>"
        
        foreach ($file in $group) {
            $fileSizeBytes = (Get-Item $file).Length  # File size in bytes
            $formattedSize = Format-FileSize -SizeInBytes $fileSizeBytes
            $totalDuplicateSize += $fileSizeBytes
            Write-Host "$file - $formattedSize"
            $htmlContent += "<li>$file - $formattedSize</li>"
        }
        
        $htmlContent += "</ul></li>"
    }
    
    $formattedTotalSize = Format-FileSize -SizeInBytes $totalDuplicateSize
    $htmlContent += "</ul><h2>Total Duplicate Size: $formattedTotalSize</h2></body></html>"
    
    # Save report to HTML file
    $htmlFilePath = "$(Get-Location)\DuplicateFilesReport.html"
    $htmlContent | Out-File -FilePath $htmlFilePath -Encoding UTF8
    Write-Host "Duplicate files report saved to: $htmlFilePath" -ForegroundColor Cyan
    Write-Host "Total duplicate file size: $formattedTotalSize" -ForegroundColor Cyan
    
    if ($DeleteDuplicates) {
        foreach ($group in $duplicateFiles) {
            $duplicates = $group[1..($group.Length - 1)]
            
            foreach ($duplicate in $duplicates) {
                Remove-Item -Path $duplicate -Force
                Write-Host "Deleted: $duplicate" -ForegroundColor Red
            }
        }
    }
} else {
    Write-Host "No duplicate files found." -ForegroundColor Green
}
