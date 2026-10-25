[app]
title = M3U8DownloaderPro
project_dir = src
input_file = src/m3u8_downloader/gui_entry.py
exec_directory = dist
project_file = 
icon =

[python]
packages = Nuitka==4.1.1
android_packages = buildozer==1.6.0,cython==0.29.33

[qt]
qml_files = m3u8_downloader/gui/qml/Main.qml,m3u8_downloader/gui/qml/components/EmptyState.qml,m3u8_downloader/gui/qml/components/Icon.qml,m3u8_downloader/gui/qml/components/PrimaryButton.qml,m3u8_downloader/gui/qml/components/ProgressTrack.qml,m3u8_downloader/gui/qml/components/SecondaryButton.qml,m3u8_downloader/gui/qml/components/SidebarButton.qml,m3u8_downloader/gui/qml/components/StatusBadge.qml,m3u8_downloader/gui/qml/components/StyledCheckBox.qml,m3u8_downloader/gui/qml/components/StyledComboBox.qml,m3u8_downloader/gui/qml/components/StyledSpinBox.qml,m3u8_downloader/gui/qml/components/StyledTextArea.qml,m3u8_downloader/gui/qml/components/StyledTextField.qml,m3u8_downloader/gui/qml/dialogs/BatchDialog.qml,m3u8_downloader/gui/qml/pages/CompletedPage.qml,m3u8_downloader/gui/qml/pages/DownloadsPage.qml,m3u8_downloader/gui/qml/pages/SettingsPage.qml,m3u8_downloader/gui/qml/theme/Theme.qml,m3u8_downloader/gui/qml/theme/qmldir
excluded_qml_plugins = QtCharts,QtDataVisualization,QtGraphs,QtLocation,QtMultimedia,QtPositioning,QtQuick3D,QtSensors,QtTest,QtWebChannel,QtWebEngine
modules = Core,DBus,Gui,Network,OpenGL,Qml,QmlMeta,QmlModels,QmlWorkerScript,Quick,QuickControls2,QuickTemplates2,Widgets
plugins = iconengines,imageformats,platforms,styles,tls

[android]
wheel_pyside = 
wheel_shiboken = 
plugins = 

[ios]
wheel_pyside = 
wheel_shiboken = 
xcframework_path = 
bundle_id = 
team_id = 
version = 1.0
deployment_target = 
entitlements = 
signing_style = Automatic
header_search_paths = 

[nuitka]
macos.permissions = 
mode = standalone
extra_args = --quiet --noinclude-qt-translations --include-package=m3u8_downloader --include-package-data=m3u8_downloader.gui --include-package=qtawesome --nofollow-import-to=qtawesome.tests --noinclude-dlls=*/qml/QtQml/StateMachine/*

[buildozer]
mode = debug
recipe_dir = 
jars_dir = 
ndk_path = 
sdk_path = 
local_libs = 
arch = 

