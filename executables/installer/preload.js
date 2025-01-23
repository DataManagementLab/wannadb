const { contextBridge, ipcRenderer } = require('electron');
//const os = require('os');
//const path = require('path');

contextBridge.exposeInMainWorld('electron', {
    selectDirectory: () => ipcRenderer.invoke('select-dirs'),
    getOS: () => ipcRenderer.invoke('get-os'),
    cloneRepo: (path) => ipcRenderer.invoke('clone-repo', path),
    createVenv: (path) => ipcRenderer.invoke('create-venv', path),
    getCurrentDirectory: () => ipcRenderer.invoke('get-current-directory'),
    checkDependencies: () => ipcRenderer.invoke('check-dependencies'),
    installDependencies: (python, git) => ipcRenderer.invoke('install-dependencies', python, git),
    endApp: () => ipcRenderer.invoke('end-app'),
    loadDependencies: (python, git) => ipcRenderer.invoke('load-dependencies', python, git),
    loadWannadbPage: () => ipcRenderer.invoke('load-wannadb-page'),
    finishPage: () => ipcRenderer.invoke('finish-page'),
    loadingDependenciesPage: () => ipcRenderer.invoke('loading-dependencies-page'),
    startInstalPage: () => ipcRenderer.invoke('start-install-page'),
});
