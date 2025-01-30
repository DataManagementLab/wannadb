const { exec } = require('child_process');
const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const semver = require('semver');
const yaml = require('js-yaml');
const configPath = path.join(__dirname, 'config.yaml');
let requiredPythonVersion = '3.10';
let requirements = [];
try {
    const configFile = fs.readFileSync(configPath, 'utf8');
    const config = yaml.load(configFile);
    requiredPythonVersion = config.requiredPythonVersion || requiredPythonVersion;
    requirements = config.requirement_files || [];
} catch (e) {
    console.error('Failed to read config.yaml:', e);
}

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
    app.quit();
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
    const pythonCommand = platform === 'win32' ? `py -${requiredPythonVersion}` : `python${requiredPythonVersion}`;
    const pythonVersion = await new Promise((resolve, reject) => {
        exec(`${pythonCommand} --version`, (error, stdout, stderr) => {
            if (error) {
                reject(error.message);
            } else if (stderr) {
                reject(stderr);
            } else {
                resolve(stdout.trim());
            }
        }).on('exit', (code) => {
            if (code !== 0) {
                throw new Error('Python not found');
            }
        });
    });

    const activateCommand = process.platform === 'win32' ? `${path.join(filePath, 'wannadb', 'venv')}\\Scripts\\activate` : ('darwin'? `source ${path.join(filePath, 'wannadb', 'venv')}/bin/activate`: `${path.join(filePath, 'wannadb', 'venv')}/bin/activate`);
    exec(`${pythonCommand} -m venv ${path.join(filePath, 'wannadb', 'venv')}`, (error, stdout, stderr) => {
        if (error) {
            throw new Error(error.message);
        }
        if (stderr) {
            return stderr;
        }
        return stdout;
    }).on('exit', (code) => {
        const installRequirements = requirements.map((requirement) => {
            return new Promise((resolve, reject) => {
                exec(`${activateCommand} && pip install -r ${path.join(filePath, 'wannadb', requirement)}`, { shell: true }, (error, stdout, stderr) => {
                }).on('exit', (code) => {
                    if (code !== 0) {
                        reject(`Failed to install ${requirement}`);
                    }
                    resolve();
                });
            });
        });

        Promise.all(installRequirements)
            .then((results) => {
                const mainWindow = BrowserWindow.getAllWindows()[0];
                mainWindow.loadFile('finish.html');
            }, (error) => {
                console.error('Error installing requirements:', error);
            })
            .catch((error) => {
                console.error('Error installing requirements:', error);
            });
    });
    const scriptContent = `
        #!/bin/bash\n
        cd ${path.join(filePath, 'wannadb')}\n
        ${activateCommand}\n
        python ${path.join(filePath, 'wannadb', 'main.py')}
        `;
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
    let pyFnished = false;
    let git = false;
    let gitFinished = false;
    try {
        const pythonCommand = process.platform === 'win32' ? `py -${requiredPythonVersion} --version` : `python${requiredPythonVersion} --version`;
        exec(pythonCommand, (error, stdout, stderr) => {
        }).on('exit', (code) => {
            if (code === 0) {
                python = true;
            }
            pyFnished = true;
        });
    } catch (error) {
        python = false;
        pyFnished = true;
    }
    try {
        exec('git --version', (error, stdout, stderr) => {
        }).on('exit', (code) => {
            if (code === 0) {
                git = true;
            }
            gitFinished = true;
        });
    } catch (error) {
        git = false;
        gitFinished = true;
    }
    while (!pyFnished || !gitFinished) {
        await new Promise((resolve) => setTimeout(resolve, 100));
    }
    return { python, git };
});

ipcMain.handle('install-dependencies', async (event, python, git) => {
    const installPythonAndGit = async () => {
        const platform = process.platform;

        if (platform === 'win32') {
            if (!python) {
                exec(`winget install -e --id Python.Python.${requiredPythonVersion.replace('.', '')}`, (error, stdout, stderr) => {
                    if (error) {
                        throw new Error(error.message);
                    }
                    if (stderr) {
                        console.error(stderr);
                    }
                    console.log(stdout);
                }).on('exit', (code) => {
                    exec(`winget install -e --id Python.Python.${requiredPythonVersion.replace('.', '')}.PythonDevelopment`, (error, stdout, stderr) => {
                        if (error) {
                            throw new Error(error.message);
                        }
                        if (stderr) {
                            console.error(stderr);
                        }
                        console.log(stdout);
                    }).on('exit', (code) => {
                        if (!git) {
                            exec('winget install -e --id Git.Git', (error, stdout, stderr) => {
                                if (error) {
                                throw new Error(error.message);
                                }
                                if (stderr) {
                                console.error(stderr);
                                }
                                console.log(stdout);
                            }).on('exit', (code) => {
                                if (code === 0) {
                                    nextPage();
                                }
                            });
                        }
                        else {
                            nextPage();
                        }
                    });
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
                }).on('exit', (code) => {
                    if (code === 0) {
                        nextPage();
                    }
                });
            }
        }
        else if (platform === 'darwin') {
            console.log(python, git);
            if (!python) {
                exec(`brew install python@${requiredPythonVersion}`, (error, stdout, stderr) => {
                    if (error) {
                        throw new Error(error.message);
                    }
                    if (stderr) {
                        console.error(stderr);
                    }
                    console.log(stdout);
                }).on('exit', (code) => {
                    exec(`brew link --force python@${requiredPythonVersion}`, (error, stdout, stderr) => {
                    if (error) {
                        throw new Error(error.message);
                    }
                    if (stderr) {
                        console.error(stderr);
                    }
                    console.log(stdout);
                    }).on('exit', (code) => {
                        if (!git) {
                            exec('brew install git', (error, stdout, stderr) => {
                                if (error) {
                                    throw new Error(error.message);
                                }
                                if (stderr) {
                                    console.error(stderr);
                                }
                                console.log(stdout);
                            }).on('exit', (code) => {
                                if (code === 0) {
                                    nextPage();
                                }
                            });
                        }
                        else {
                            nextPage();
                        }
                    });
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
                }).on('exit', (code) => {
                    if (code === 0) {
                        nextPage();
                    }
                });
            }
        }
        else if (platform === 'linux') {
            if (!python) {
                exec(`sudo apt-get update && sudo apt-get install -y python${requiredPythonVersion}`, (error, stdout, stderr) => {
                    if (error) {
                        throw new Error(error.message);
                    }
                    if (stderr) {
                        console.error(stderr);
                    }
                    console.log(stdout);
                }).on('exit', (code) => {
                    exec(`sudo apt-get install -y python${requiredPythonVersion}-venv`, (error, stdout, stderr) => {
                        if (error) {
                            throw new Error(error.message);
                        }
                        if (stderr) {
                            console.error(stderr);
                        }
                        console.log(stdout);
                    }).on('exit', (code) => {
                        if (!git) {
                            exec('sudo apt-get install -y git', (error, stdout, stderr) => {
                                if (error) {
                                    throw new Error(error.message);
                                }
                                if (stderr) {
                                    console.error(stderr);
                                }
                                console.log(stdout);
                            }).on('exit', (code) => {
                                if (code === 0) {
                                    nextPage();
                                }
                            });
                        }
                        else {
                            nextPage();
                        }
                    });
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
                }).on('exit', (code) => {
                    if (code === 0) {
                        nextPage();
                    }
                });
            }
        } else {
            throw new Error('Unsupported platform');
        }
    };

    const nextPage = () => {
        const mainWindow = BrowserWindow.getAllWindows()[0];
        mainWindow.loadFile('index.html');
    };

    installPythonAndGit();
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