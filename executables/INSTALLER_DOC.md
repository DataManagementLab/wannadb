# WannaDB Installer

Welcome to the WannaDB Installer documentation. This guide will help you configure and update the installer if needed. This project handles the installer for WannaDB.
It uses [Electron](https://www.electronjs.org/docs) and JavaScript.

## Project Structure

The WannaDB Installer project is organized as follows:

```
/executables
|-- /bin
|   |-- installer.sh
|-- /installer
|   |-- dependencies.html
|   |-- finish.html
|   |-- index.html
|   |-- loading_dependencies.html
|   |-- loading_wannadb.html
|   |-- main.js
|   |-- package-lock.json
|   |-- package.json
|   |-- preload.js
|   |-- config.yaml
|-- INSTALLER_DOC.md
```

- **/bin**: Contains the main executable script for the installer.
- **/installer**: Contains the html and JavaScript files to build the project.

## Adjusting the Project

If WannaDB has been updated, you may need to adjust the installer project accordingly. Here are the steps to follow:

1. **Update Configuration**: Modify the `config.yaml` file in the `/config` directory to reflect any new settings or parameters required by the updated version of WannaDB.

3. **Modify Dependencies**: If new dependencies are needed in addition to Python, Git, and the ones listed in `requirements.txt`, update the `check-dependencies` and `install-dependencies` methods accordingly.

4. **Testing**: After making the necessary adjustments, thoroughly test the installer to ensure it works correctly with the new version of WannaDB.

By following these steps, you can keep the WannaDB Installer project up to date with any changes made to WannaDB.

