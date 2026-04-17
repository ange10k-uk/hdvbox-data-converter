"use strict";

const logBox = document.getElementById('log-box');
const engineStatus = document.getElementById('engine-status');
const convertBtn = document.getElementById('convert-btn');
const fileInput = document.getElementById('file-input');
const dropZone = document.getElementById('drop-zone');
const fileNameHint = document.getElementById('file-name');
const langRuBtn = document.getElementById('lang-ru');
const langEnBtn = document.getElementById('lang-en');
const helpBtn = document.getElementById('help-btn');
const modalOverlay = document.getElementById('modal-overlay');
const modalClose = document.getElementById('modal-close');

let pyodide = null;
let isEngineReady = false;
let selectedFile = null;
let currentLang = 'ru';

const TRANSLATIONS = {
    ru: {
        "page-title": "HDVBox Онлайн Конвертер",
        "logo-title": "HDVBox",
        "logo-subtitle": "Конвертер данных от UKay",
        "tg-link": "Группа Telegram",
        "hero-desc": "Конвертируйте базы данных HDVideoBox в формате fsdb (db_backup.fsdb) в формат JSON для HDAlfaBox >= v1.0.0 прямо в браузере.",
        "drop-title": "Перетащите базу данных сюда",
        "drop-hint": "или нажмите для выбора файла",
        "config-title": "Конфигурация",
        "pretty-json": "Красивый формат JSON",
        "prefixes-label": "Добавить префиксы источников (напр. [H] - HDRezka, [F] - Filmix)",
        "sections-title": "Разделы для экспорта",
        "section-fav": "Избранное",
        "section-later": "На будущее",
        "section-done": "Завершенное",
        "section-process": "В процессе",
        "btn-start": "НАЧАТЬ ЭКСПОРТ",
        "engine-status": "Статус движка:",
        "status-init": "Инициализация...",
        "status-ready": "Готов",
        "status-error": "Ошибка",
        "log-wait": "Ожидание загрузки движка...",
        "instr-title": "Как перенести данные",
        "footer-built": "Создано для HDAlfaBox • Поддержка HDAlfaBox >= v1.0.0",
        "footer-secure": "Приватно и безопасно.",
        // Log messages
        "msg-init-py": "Инициализация Python движка (Pyodide)...",
        "msg-load-mod": "Загрузка стандартных модулей...",
        "msg-inject-logic": "Внедрение логики конвертера...",
        "msg-fetch-fail": "Ошибка загрузки (возможно CORS/локальный файл). Пробую запасной вариант...",
        "msg-load-fail": "Не удалось загрузить converter.py. Пожалуйста, запустите 'run_web_app.bat' для запуска локального сервера и перейдите на http://localhost:8000/web/",
        "msg-ready": "Движок готов, конвертер загружен.",
        "msg-file-sel": "Файл выбран: ",
        "msg-start-conv": "Запуск процесса конвертации...",
        "msg-exec-py": "Выполнение Python логики...",
        "msg-success": "Конвертация успешна! Запущена автоматическая загрузка.",
        "msg-manual": "Если файл не скачался, используйте кнопку «Скачать вручную» выше.",
        "msg-btn-manual": "Скачать сконвертированный JSON (вручную)",
        "msg-error": "Ошибка при конвертации: ",
        "msg-err-section": "Необходимо выбрать хотя бы один раздел.",
        // Instructions
        "instr-link": "Инструкция",
        "instr-step1": "<strong>Экспорт из старого приложения:</strong> Настройки → Сохраненные данные → Сохранить историю. Сохраните файл `db_backup.fsdb`.",
        "instr-step2": "<strong>Конвертация файла:</strong> Загрузите файл выше, нажмите <strong>НАЧАТЬ ЭКСПОРТ</strong> и скачайте полученный `.json` файл.",
        "instr-step3": "<strong>Импорт в новое приложение:</strong> Откройте новое приложение → Настройки → Сохраненные данные → Восстановить историю. Выберите сконвертированный `.json` файл."
    },
    en: {
        "page-title": "HDVBox Online Data Converter",
        "logo-title": "HDVBox",
        "logo-subtitle": "Data Converter by UKay",
        "tg-link": "Join Telegram",
        "hero-desc": "Convert your HDVideoBox databases in fsbd format (db_backup.fsdb) to JSON format for HDAlfaBox >= v1.0.0 in your browser.",
        "drop-title": "Drag & Drop Database",
        "drop-hint": "or click to browse your files",
        "config-title": "Configuration",
        "pretty-json": "Pretty Print JSON",
        "prefixes-label": "Add source prefixes (e.g., [H] - HDRezka, [F] - Filmix)",
        "sections-title": "Export Sections",
        "section-fav": "Favorites",
        "section-later": "ForLater",
        "section-done": "Finished",
        "section-process": "In Process",
        "btn-start": "START EXPORT",
        "engine-status": "Runtime Engine Status:",
        "status-init": "Initializing...",
        "status-ready": "Ready",
        "status-error": "Error",
        "log-wait": "Waiting for engine to load...",
        "instr-title": "How to Migrate",
        "footer-built": "Built for HDAlfaBox • Supported HDAlfaBox >= v1.0.0",
        "footer-secure": "Private & Secure.",
        // Log messages
        "msg-init-py": "Initializing Python engine (Pyodide)...",
        "msg-load-mod": "Loading standard modules...",
        "msg-inject-logic": "Injecting converter logic...",
        "msg-fetch-fail": "Fetch failed (likely CORS/local file issue). Trying local fallback...",
        "msg-load-fail": "Could not load converter.py. Please run 'run_web_app.bat' to start the local server and visit http://localhost:8000/web/",
        "msg-ready": "Engine ready and converter loaded.",
        "msg-file-sel": "File selected: ",
        "msg-start-conv": "Starting conversion process...",
        "msg-exec-py": "Executing Python logic...",
        "msg-success": "Conversion successful! Automatic download attempted.",
        "msg-manual": "If the file didn't download, use the 'Manual Link' button above.",
        "msg-btn-manual": "Download Converted JSON (Manual Link)",
        "msg-error": "Error during conversion: ",
        "msg-err-section": "At least one section must be selected.",
        // Instructions
        "instr-link": "How to Migrate",
        "instr-step1": "<strong>Export from the old app:</strong> Settings → Saved data → Backup History. Save the `db_backup.fsdb` file.",
        "instr-step2": "<strong>Convert the file:</strong> Upload the file above, click <strong>START EXPORT</strong>, and download the `.json` file.",
        "instr-step3": "<strong>Import to the new app:</strong> Open the new app → Settings → Saved data → Restore History. Select the converted `.json` file."
    }
};

function t(key) {
    return TRANSLATIONS[currentLang][key] || key;
}

function updateUI() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (TRANSLATIONS[currentLang][key]) {
            el.innerHTML = TRANSLATIONS[currentLang][key];
        }
    });

    // Update Instructions
    const instrContainer = document.getElementById('instructions-container');
    instrContainer.innerHTML = `
        <div class="step">
            <span class="step-num">1</span>
            <div class="step-content"><p>${t('instr-step1')}</p></div>
        </div>
        <div class="step">
            <span class="step-num">2</span>
            <div class="step-content"><p>${t('instr-step2')}</p></div>
        </div>
        <div class="step">
            <span class="step-num">3</span>
            <div class="step-content"><p>${t('instr-step3')}</p></div>
        </div>
    `;

    // Update dynamic status if needed
    if (isEngineReady) {
        engineStatus.textContent = t('status-ready');
    } else if (engineStatus.textContent !== t('status-init')) {
        engineStatus.textContent = t('status-error');
    }

    // Update document lang
    document.documentElement.lang = currentLang;
}

function setLanguage(lang) {
    currentLang = lang;
    langRuBtn.classList.toggle('active', lang === 'ru');
    langEnBtn.classList.toggle('active', lang === 'en');
    updateUI();
    localStorage.setItem('preferred-lang', lang);
}

function log(message, type = 'info') {
    const div = document.createElement('div');
    div.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    if (type === 'error') div.style.color = 'var(--error)';
    if (type === 'success') div.style.color = 'var(--success)';
    if (type === 'warning') div.style.color = '#fbbf24';
    logBox.prepend(div);
}

// Initialize Pyodide
async function initPyodide() {
    try {
        log(t('msg-init-py'));
        pyodide = await loadPyodide();

        log(t('msg-load-mod'));
        await pyodide.loadPackage("sqlite3");

        log(t('msg-inject-logic'));
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
            log(t('msg-fetch-fail'), "warning");
            try {
                const fallbackResponse = await fetch('converter.py');
                if (fallbackResponse.ok) {
                    script = await fallbackResponse.text();
                }
            } catch (innerErr) { }
        }

        if (!script) {
            throw new Error(t('msg-load-fail'));
        }

        pyodide.runPython(script);
        isEngineReady = true;

        engineStatus.textContent = t('status-ready');
        engineStatus.classList.add('ready');
        log(t('msg-ready'), "success");
        updateButtonState();
    } catch (err) {
        log(`${t('status-error')}: ${err.message}`, "error");
        engineStatus.textContent = t('status-error');
        isEngineReady = false;
        updateButtonState();
    }
}

function updateButtonState() {
    convertBtn.disabled = !isEngineReady || !selectedFile;
}

// File Handlers
document.querySelectorAll('.config-pane').forEach(el => {
    el.onclick = (e) => e.stopPropagation();
});

dropZone.onclick = () => {
    if (!convertBtn.disabled || engineStatus.textContent === t('status-ready')) {
        fileInput.click();
    }
};

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
    fileNameHint.textContent = `${t('msg-file-sel')}${file.name}`;
    log(`${t('msg-file-sel')}${file.name}`);
    updateButtonState();
}

// Language Switchers
langRuBtn.onclick = () => setLanguage('ru');
langEnBtn.onclick = () => setLanguage('en');

// Modal Handlers
helpBtn.onclick = () => modalOverlay.classList.add('active');
modalClose.onclick = () => modalOverlay.classList.remove('active');
modalOverlay.onclick = (e) => {
    if (e.target === modalOverlay) {
        modalOverlay.classList.remove('active');
    }
};

// Conversion Logic
convertBtn.onclick = async (e) => {
    e.stopPropagation();
    if (!isEngineReady || !selectedFile) return;

    const linkContainer = document.getElementById('download-link-container');
    if (linkContainer) linkContainer.innerHTML = '';

    const btnText = convertBtn.querySelector('.btn-text');
    const loader = convertBtn.querySelector('.loader');

    try {
        convertBtn.disabled = true;
        btnText.style.opacity = '0.5';
        loader.style.display = 'block';
        log(t('msg-start-conv'));

        const pretty = document.getElementById('pretty-print').checked;
        const usePrefixes = document.getElementById('use-prefixes').checked;
        const sectionEls = Array.from(document.querySelectorAll('input[name="sections"]:checked'));
        const sections = sectionEls.map(c => c.value);

        if (sections.length === 0) {
            throw new Error(t('msg-err-section'));
        }

        const finalSections = sections.length === 4 ? ["all"] : sections;

        const arrayBuffer = await selectedFile.arrayBuffer();
        const uint8Array = new Uint8Array(arrayBuffer);

        const inPath = "/input.db";
        const outPath = "/export.json";
        pyodide.FS.writeFile(inPath, uint8Array);

        log(t('msg-exec-py'));

        pyodide.globals.set("in_path", inPath);
        pyodide.globals.set("out_path", outPath);
        pyodide.globals.set("is_pretty", pretty);
        pyodide.globals.set("use_prefixes", usePrefixes);
        pyodide.globals.set("fav_sections", pyodide.toPy(finalSections));

        const pythonCode = `
res_msg = process_export(
    db_path_str=in_path,
    out_path_str=out_path,
    pretty=is_pretty,
    favorites_section=fav_sections,
    use_prefixes=use_prefixes
)
res_msg
        `;

        const resultMsg = await pyodide.runPythonAsync(pythonCode);
        log("Python: \n" + resultMsg, "success");

        const outputData = pyodide.FS.readFile(outPath, { encoding: "utf8" });

        const now = new Date();
        const dateStr = now.getFullYear().toString() +
            (now.getMonth() + 1).toString().padStart(2, '0') +
            now.getDate().toString().padStart(2, '0');
        const timeStr = now.getHours().toString().padStart(2, '0') + "-" +
            now.getMinutes().toString().padStart(2, '0') + "-" +
            now.getSeconds().toString().padStart(2, '0');

        const downloadName = `videobox_backup_hystory_converted_${dateStr}_${timeStr}.json`;

        downloadFile(outputData, downloadName, "application/json");

        const base64Data = btoa(unescape(encodeURIComponent(outputData)));
        const dataUri = `data:application/json;charset=utf-8;base64,${base64Data}`;

        if (linkContainer) {
            const a = document.createElement('a');
            a.href = dataUri;
            a.download = downloadName;
            a.className = 'manual-download-link';
            a.innerHTML = `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 8px; vertical-align: middle;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg> ${t('msg-btn-manual')}`;
            linkContainer.appendChild(a);
        }

        log(t('msg-success'), "success");
        log(t('msg-manual'));

    } catch (err) {
        log(`${t('msg-error')}${err.message}`, "error");
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
const savedLang = localStorage.getItem('preferred-lang') || 'ru';
setLanguage(savedLang);
initPyodide();
