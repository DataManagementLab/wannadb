const { exec } = require('child_process');
const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const path = require('path');

function createWindow() {
    const mainWindow = new BrowserWindow({
        width: 600,
        height: 315,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'), // Ensure this path is correct
            contextIsolation: true,
            enableRemoteModule: false,
            nodeIntegration: false
        }
    });

    mainWindow.loadFile('index.html');
}

app.on('ready', createWindow);

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
    }
});

ipcMain.handle('select-dirs', async (event) => {
    const result = await dialog.showOpenDialog({
        properties: ['openDirectory']
    });
    return result.filePaths[0];
});

ipcMain.handle('clone-repo', async (event, path) => {
    exec(`git clone https://github.com/DataManagementLab/wannadb.git ${path}`, (error, stdout, stderr) => {
        if (error) {
            return error.message;
        }
        if (stderr) {
            return stderr;
        }
        return stdout;
    });
});

ipcMain.handle('create-venv', async (event, path) => {
    const pythonVersion = await new Promise((resolve, reject) => {
        exec('python3 --version', (error, stdout, stderr) => {
            if (error) {
                reject(error.message);
            } else if (stderr) {
                reject(stderr);
            } else {
                resolve(stdout.trim());
            }
        });
    });

    const versionMatch = pythonVersion.match(/^Python (\d+\.\d+\.\d+)/);
    if (!versionMatch || parseFloat(versionMatch[1]) < 3.10) {
        throw new Error('Python 3.10 or newer is required.');
    }
    exec(`python3 -m venv ${path}`, (error, stdout, stderr) => {
        if (error) {
            return error.message;
        }
        if (stderr) {
            return stderr;
        }
        return stdout;
    });
    const activateCommand = process.platform === 'win32' ? `${path}\\Scripts\\activate` : ('darwin'? `source ${path}/bin/activate`: `${path}/bin/activate`);
    exec(`${activateCommand} && pip install -r requirements.txt`, { shell: true }, (error, stdout, stderr) => {
        if (error) {
            return error.message;
        }
        if (stderr) {
            return stderr;
        }
        return stdout;
    });
});

ipcMain.handle('get-current-directory', async (event) => {
    return app.getAppPath();
});