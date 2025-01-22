const { contextBridge, ipcRenderer } = require('electron');
//const os = require('os');
//const path = require('path');

contextBridge.exposeInMainWorld('electron', {
    selectDirectory: () => ipcRenderer.invoke('select-dirs'),
    getOS: () => 'darwin',
    cloneRepo: (path) => ipcRenderer.invoke('clone-repo', path),
    createVenv: (path) => ipcRenderer.invoke('create-venv', path),
    getCurrentDirectory: () => ipcRenderer.invoke('get-current-directory'),
});
