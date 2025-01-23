const { exec } = require('child_process');
const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const semver = require('semver');

function createWindow() {
    const mainWindow = new BrowserWindow({
        width: 600,
        height: 315,
        resizable: false,
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

ipcMain.handle('clone-repo', async (event, filePath) => {
    exec(`git clone https://github.com/DataManagementLab/wannadb.git ${path.join(filePath, 'wannadb')}`, (error, stdout, stderr) => {
        if (error) {
            return error.message;
        }
        if (stderr) {
            return stderr;
        }
        return stdout;
    });
});

ipcMain.handle('create-venv', async (event, filePath) => {
    const platform = process.platform;
    const pythonCommand = platform === 'win32' ? 'py -3.10' : 'python3.10';
    const pythonVersion = await new Promise((resolve, reject) => {
        exec(`${pythonCommand} --version`, (error, stdout, stderr) => {
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
    if (!versionMatch || semver.lt(versionMatch[1], '3.10.0')) {
        throw new Error('Python 3.10 or newer is required.');
    }
    exec(`${pythonCommand} -m venv ${path.join(filePath, 'wannadb', 'venv')}`, (error, stdout, stderr) => {
        if (error) {
            throw new Error(error.message);
        }
        if (stderr) {
            return stderr;
        }
        return stdout;
    }).on('exit', (code) => {
        const activateCommand = process.platform === 'win32' ? `${path.join(filePath, 'wannadb', 'venv')}\\Scripts\\activate` : ('darwin'? `source ${path.join(filePath, 'wannadb', 'venv')}/bin/activate`: `${path.join(filePath, 'wannadb', 'venv')}/bin/activate`);
        exec(`${activateCommand} && pip install -r ${path.join(filePath, 'wannadb', 'requirements.txt')}`, { shell: true }, (error, stdout, stderr) => {
            if (error) {
                throw new Error(error.message);
            }
            if (stderr) {
                return stderr;
            }
            return stdout;
        }).on('exit', (code) => {
            const mainWindow = BrowserWindow.getAllWindows()[0];
            mainWindow.loadFile('finish.html');
        });
    });
    const scriptContent = `#!/bin/bash\nsource ${path.join(filePath, 'wannadb', 'venv')}/bin/activate\npython ${path.join(filePath, 'wannadb', 'main.py')}`;
    const scriptFilePath = path.join(filePath, 'WannaDB.sh');
    fs.writeFile(scriptFilePath, scriptContent, { mode: 0o755 }, (err) => {
        if (err) {
            throw new Error(err.message);
        }
        if (process.platform === 'win32') {
            exec(`powershell -Command "Start-Process cmd -ArgumentList '/c ${scriptFilePath}' -Verb RunAs"`, (error, stdout, stderr) => {
                if (error) {
                    throw new Error(error.message);
                }
                if (stderr) {
                    console.error(stderr);
                }
                console.log(stdout);
            });
        } else {
            exec(`chmod +x ${scriptFilePath}`, (error, stdout, stderr) => {
                if (error) {
                    throw new Error(error.message);
                }
                if (stderr) {
                    console.error(stderr);
                }
                console.log(stdout);
            });
        }
    });
    return 'Virtual environment created successfully.';
});

ipcMain.handle('get-current-directory', async (event) => {
    return app.getAppPath();
});

ipcMain.handle('get-os', async (event) => {
    return process.platform;
});

ipcMain.handle('check-dependencies', async (event) => {
    let python = false;
    try {
        const pythonVersion = await new Promise((resolve, reject) => {
            const pythonCommand = process.platform === 'win32' ? 'py -3.10 --version' : 'python3.10 --version';
            exec(pythonCommand, (error, stdout, stderr) => {
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
        if (!versionMatch || semver.lt(versionMatch[1], '3.10.0')) {
            python = false;
        }
        else {
            python = true;
        }
    } catch (error) {
        python = false;
    }
    let git = false;
    try {
        await new Promise((resolve, reject) => {
            exec('git --version', (error, stdout, stderr) => {
                if (error) {
                    reject(error.message);
                } else if (stderr) {
                    reject(stderr);
                } else {
                    resolve();
                }
            });
        });
        git = true;
    } catch (error) {
        git = false;
    }
    return { python, git };
});

ipcMain.handle('install-dependencies', async (event, python, git) => {
    const installPythonAndGit = async () => {
        const platform = process.platform;

        if (platform === 'win32') {
            if (!python) {
                exec('winget install -e --id Python.Python.3.10', (error, stdout, stderr) => {
                    if (error) {
                        throw new Error(error.message);
                    }
                    if (stderr) {
                        console.error(stderr);
                    }
                    console.log(stdout);
                }).on('exit', (code) => {
                    exec('winget install -e --id Python.Python.3.10.PythonDevelopment', (error, stdout, stderr) => {
                        if (error) {
                            throw new Error(error.message);
                        }
                        if (stderr) {
                            console.error(stderr);
                        }
                        console.log(stdout);
                    });
                    if (!git) {
                        exec('winget install -e --id Git.Git', (error, stdout, stderr) => {
                            if (error) {
                            throw new Error(error.message);
                            }
                            if (stderr) {
                            console.error(stderr);
                            }
                            console.log(stdout);
                        });
                    }
                });
            }
            else if (!git) {
                exec('winget install -e --id Git.Git', (error, stdout, stderr) => {
                    if (error) {
                    throw new Error(error.message);
                    }
                    if (stderr) {
                    console.error(stderr);
                    }
                    console.log(stdout);
                });
            }
        }
        else if (platform === 'darwin') {
            console.log(python, git);
            if (!python) {
                exec('brew install python@3.10', (error, stdout, stderr) => {
                    if (error) {
                    throw new Error(error.message);
                    }
                    if (stderr) {
                    console.error(stderr);
                    }
                    console.log(stdout);
                }).on('exit', (code) => {
                    exec('brew link --force python@3.10', (error, stdout, stderr) => {
                    if (error) {
                        throw new Error(error.message);
                    }
                    if (stderr) {
                        console.error(stderr);
                    }
                    console.log(stdout);
                    });
                    if (!git) {
                    exec('brew install git', (error, stdout, stderr) => {
                        if (error) {
                        throw new Error(error.message);
                        }
                        if (stderr) {
                        console.error(stderr);
                        }
                        console.log(stdout);
                    });
                    }
                });
            }
            else if (!git) {
                exec('brew install git', (error, stdout, stderr) => {
                    if (error) {
                    throw new Error(error.message);
                    }
                    if (stderr) {
                    console.error(stderr);
                    }
                    console.log(stdout);
                });
            }
        }
        else if (platform === 'linux') {
            if (!python) {
                exec('sudo apt-get update && sudo apt-get install -y python3.10', (error, stdout, stderr) => {
                    if (error) {
                        throw new Error(error.message);
                    }
                    if (stderr) {
                        console.error(stderr);
                    }
                    console.log(stdout);
                }).on('exit', (code) => {
                    exec('sudo apt-get install -y python3.10-venv', (error, stdout, stderr) => {
                        if (error) {
                            throw new Error(error.message);
                        }
                        if (stderr) {
                            console.error(stderr);
                        }
                        console.log(stdout);
                    });
                    if (!git) {
                        exec('sudo apt-get install -y git', (error, stdout, stderr) => {
                            if (error) {
                            throw new Error(error.message);
                            }
                            if (stderr) {
                            console.error(stderr);
                            }
                            console.log(stdout);
                        });
                    }
                });
            }
            else if (!git) {
                exec('sudo apt-get install -y git', (error, stdout, stderr) => {
                    if (error) {
                        throw new Error(error.message);
                    }
                    if (stderr) {
                        console.error(stderr);
                    }
                    console.log(stdout);
                });
            }
        } else {
            throw new Error('Unsupported platform');
        }
    };

    installPythonAndGit().then(() => {
        const mainWindow = BrowserWindow.getAllWindows()[0];
        mainWindow.loadFile('index.html');
        return { python, git };
    });
});

ipcMain.handle('end-app', async (event) => {
    app.quit();
    if (process.platform === 'darwin') {
        app.quit();
    }
});

ipcMain.handle('load-dependencies', async (event, python, git) => {
    const mainWindow = BrowserWindow.getAllWindows()[0];
    const url = `file://${path.join(__dirname, 'dependencies.html')}?python=${python}&git=${git}`;
    mainWindow.loadURL(url);
});

ipcMain.handle('load-wannadb-page', async (event) => {
    const mainWindow = BrowserWindow.getAllWindows()[0];
    mainWindow.loadFile('loading_wannadb.html');
});

ipcMain.handle('finish-page', async (event) => {
    const mainWindow = BrowserWindow.getAllWindows()[0];
    mainWindow.loadFile('finish.html');
});

ipcMain.handle('loading-dependencies-page', async (event) => {
    const mainWindow = BrowserWindow.getAllWindows()[0];
    mainWindow.loadFile('loading_dependencies.html');
});

ipcMain.handle('start-install-page', async (event) => {
    const mainWindow = BrowserWindow.getAllWindows()[0];
    mainWindow.loadFile('index.html');
});