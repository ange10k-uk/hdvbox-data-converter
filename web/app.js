"use strict";

const logBox = document.getElementById('log-box');
const engineStatus = document.getElementById('engine-status');
const convertBtn = document.getElementById('convert-btn');
const fileInput = document.getElementById('file-input');
const dropZone = document.getElementById('drop-zone');
const fileNameHint = document.getElementById('file-name');

let pyodide = null;
let isEngineReady = false;
let selectedFile = null;

function log(message, type = 'info') {
    const div = document.createElement('div');
    div.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    if (type === 'error') div.style.color = 'var(--error)';
    if (type === 'success') div.style.color = 'var(--success)';
    logBox.prepend(div);
}

// Initialize Pyodide
async function initPyodide() {
    try {
        log("Initializing Python engine (Pyodide)...");
        pyodide = await loadPyodide();
        
        log("Loading standard modules...");
        
        // Fetch converter.py content
        log("Injecting converter logic...");
        let script = "";
        try {
            const response = await fetch('../converter.py');
            if (response.ok) {
                script = await response.text();
            } else {
                const fallbackResponse = await fetch('converter.py');
                if (fallbackResponse.ok) {
                    script = await fallbackResponse.text();
                }
            }
        } catch (fetchErr) {
            log("Fetch failed (likely CORS/local file issue). Trying local fallback...", "warning");
            try {
                const fallbackResponse = await fetch('converter.py');
                if (fallbackResponse.ok) {
                    script = await fallbackResponse.text();
                }
            } catch (innerErr) {}
        }

        if (!script) {
            throw new Error("Could not load converter.py. If running locally, please use a web server (e.g., 'python -m http.server').");
        }

        pyodide.runPython(script);
        isEngineReady = true;

        engineStatus.textContent = "Ready";
        engineStatus.classList.add('ready');
        log("Engine ready and converter loaded.", "success");
        updateButtonState();
    } catch (err) {
        log(`Failed to initialize: ${err.message}`, "error");
        engineStatus.textContent = "Error";
        isEngineReady = false;
        updateButtonState();
    }
}

function updateButtonState() {
    convertBtn.disabled = !isEngineReady || !selectedFile;
}

// File Handlers
dropZone.onclick = () => fileInput.click();

dropZone.ondragover = (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
};

dropZone.ondragleave = () => {
    dropZone.classList.remove('dragover');
};

dropZone.ondrop = (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
        handleFile(e.dataTransfer.files[0]);
    }
};

fileInput.onchange = (e) => {
    if (e.target.files.length > 0) {
        handleFile(e.target.files[0]);
    }
};

function handleFile(file) {
    selectedFile = file;
    fileNameHint.textContent = `Selected: ${file.name}`;
    log(`File selected: ${file.name}`);
    updateButtonState();
}

// Conversion Logic
convertBtn.onclick = async () => {
    if (!isEngineReady || !selectedFile) return;

    const btnText = convertBtn.querySelector('.btn-text');
    const loader = convertBtn.querySelector('.loader');
    
    try {
        convertBtn.disabled = true;
        btnText.style.opacity = '0.5';
        loader.style.display = 'block';
        log("Starting conversion process...");

        // Get options
        const pretty = document.getElementById('pretty-print').checked;
        const sectionEls = Array.from(document.querySelectorAll('input[name="sections"]:checked'));
        const sections = sectionEls.map(c => c.value);
        
        if (sections.length === 0) {
            throw new Error("At least one section must be selected.");
        }

        // Standardize sections
        const finalSections = sections.length === 4 ? ["all"] : sections;

        // Read file content
        const arrayBuffer = await selectedFile.arrayBuffer();
        const uint8Array = new Uint8Array(arrayBuffer);
        
        // Write to virtual filesystem
        const inPath = "/input.db";
        const outPath = "/export.json";
        pyodide.FS.writeFile(inPath, uint8Array);
        
        log("Executing Python logic...");
        
        // Inject values via globals for safety
        pyodide.globals.set("in_path", inPath);
        pyodide.globals.set("out_path", outPath);
        pyodide.globals.set("is_pretty", pretty);
        pyodide.globals.set("fav_sections", pyodide.toPy(finalSections));

        const pythonCode = `
res_msg = process_export(
    db_path_str=in_path,
    out_path_str=out_path,
    pretty=is_pretty,
    favorites_section=fav_sections
)
res_msg
        `;
        
        const resultMsg = await pyodide.runPythonAsync(pythonCode);
        log("Python: " + resultMsg, "success");

        // Read resulting file
        const outputData = pyodide.FS.readFile(outPath, { encoding: "utf8" });
        
        // Download trigger
        downloadFile(outputData, "export.json", "application/json");
        log("Conversion successful! Download started.", "success");

    } catch (err) {
        log(`Error during conversion: ${err.message}`, "error");
    } finally {
        convertBtn.disabled = false;
        btnText.style.opacity = '1';
        loader.style.display = 'none';
    }
};

function downloadFile(content, fileName, contentType) {
    const a = document.createElement("a");
    const file = new Blob([content], { type: contentType });
    a.href = URL.createObjectURL(file);
    a.download = fileName;
    a.click();
    URL.revokeObjectURL(a.href);
}

// Start
initPyodide();
