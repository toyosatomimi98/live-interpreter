; ===========================================================================
;  live-interpreter（同声传译）Windows 安装包
;
;  编译： build_installer.bat      （或直接 ISCC.exe installer\live-interpreter.iss）
;  依赖： Inno Setup 6            https://jrsoftware.org/isdl.php
;
;  说明：
;   * 每个用户安装，不需要管理员权限，默认装到 %LOCALAPPDATA%\Programs\live-interpreter
;   * 安装包本身很小：装完在“完成”页勾选即可下载 Python 依赖 + 语音模型（约 1~2 GB）
;   * 录音/笔记保存位置、DeepSeek API key 在安装向导里配置，写进
;     %APPDATA%\live-interpreter\config.json，程序启动时读取
; ===========================================================================

#define AppName "同声传译"
#define AppNameEn "live-interpreter"
#define AppVersion "1.0.0"
#define AppVersionQuad "1.0.0.0"
#define AppPublisher "toyosatomimi98"
#define AppURL "https://github.com/toyosatomimi98/live-interpreter"
#define AppExeName "启动同声传译.exe"

[Setup]
AppId={{8E4C1A72-3B5D-4E90-9C21-7A6F0D4B8E52}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}（{#AppNameEn}）
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
AppComments=实时英语→中文同声传译：本地识别 + DeepSeek 翻译 + 中文语音播报 + 自动存笔记
VersionInfoVersion={#AppVersionQuad}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} 安装程序
DefaultDirName={localappdata}\Programs\{#AppNameEn}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=..\release
OutputBaseFilename=同声传译-{#AppVersion}-安装包
SetupIconFile=..\assets\app.ico
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
ShowLanguageDialog=no
SetupLogging=yes
UsePreviousAppDir=yes

[Languages]
Name: "chinese"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; 程序本体（.venv / 模型 / 录音 / 笔记 / 构建产物都不打包）
Source: "..\*.py";            DestDir: "{app}"; Flags: ignoreversion
Source: "..\*.bat";           DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md";       DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE";         DestDir: "{app}"; Flags: ignoreversion
Source: "..\{#AppExeName}";   DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\app.ico";  DestDir: "{app}\assets"; Flags: ignoreversion
Source: "..\assets\app.png";  DestDir: "{app}\assets"; Flags: ignoreversion
Source: "..\docs\*";          DestDir: "{app}\docs";   Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\tools\*.py";      DestDir: "{app}\tools";  Flags: ignoreversion
Source: "..\tools\*.bat";     DestDir: "{app}\tools";  Flags: ignoreversion
Source: "..\tools\version_info.txt"; DestDir: "{app}\tools"; Flags: ignoreversion

[Icons]
; {group} = 开始菜单\同声传译\（DefaultGroupName），保证图标进自己的分组，不污染开始菜单顶部
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Comment: "启动同声传译（实时字幕）"
Name: "{group}\{#AppName} - 诊断"; Filename: "{app}\诊断.bat"; WorkingDir: "{app}"; Comment: "环境体检，出问题先跑这个"
Name: "{group}\{#AppName} - 设置 API 密钥"; Filename: "{app}\设置API密钥.bat"; WorkingDir: "{app}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\{#AppNameEn}"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#AppNameEn}"; ValueType: string; ValueName: "Version"; ValueData: "{#AppVersion}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\install.bat"; Description: "立即准备运行环境（首次约 5~15 分钟，需联网下载依赖与语音模型）"; Flags: postinstall shellexec skipifsilent
Filename: "{app}\{#AppExeName}"; Description: "只启动同声传译（运行环境已就绪时选这个）"; Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
; 只清理由程序自己生成的东西；录音和笔记是用户资料，一律保留
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\_tmp"
Type: filesandordirs; Name: "{app}\build"
Type: filesandordirs; Name: "{app}\dist"

[Code]
var
  DataPage: TInputDirWizardPage;
  KeyPage: TInputQueryWizardPage;

{ 支持无人值守安装：/RECORDINGS=... /TRANSCRIPTS=... /APIKEY=... }
function GetParam(const Name: String): String;
var
  I: Integer;
begin
  Result := '';
  for I := 1 to ParamCount do
    if CompareText(Copy(ParamStr(I), 1, Length(Name) + 1), Name + '=') = 0 then
      Result := Copy(ParamStr(I), Length(Name) + 2, MaxInt);
end;

function JsonEscape(const S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
end;

procedure WriteUserConfig(const Recordings, Transcripts, ApiKey: String);
var
  Dir, Json: String;
  Lines: TArrayOfString;
begin
  Dir := ExpandConstant('{userappdata}\{#AppNameEn}');
  ForceDirectories(Dir);

  Json := '{' + #13#10;
  Json := Json + '  "install_dir": "' + JsonEscape(ExpandConstant('{app}')) + '",' + #13#10;
  Json := Json + '  "recordings_dir": "' + JsonEscape(Recordings) + '",' + #13#10;
  Json := Json + '  "transcripts_dir": "' + JsonEscape(Transcripts) + '",' + #13#10;
  if ApiKey <> '' then
    Json := Json + '  "api_key": "' + JsonEscape(ApiKey) + '",' + #13#10;
  Json := Json + '  "installed_version": "{#AppVersion}"' + #13#10;
  Json := Json + '}' + #13#10;

  SetArrayLength(Lines, 1);
  Lines[0] := Json;
  if not SaveStringsToUTF8File(Dir + '\config.json', Lines, False) then
    MsgBox('用户配置写入失败（不影响安装）：之后可以在程序里重新设置。',
           mbInformation, MB_OK);

  { 顺手把两个目录建出来，用户立刻能看到 }
  ForceDirectories(Recordings);
  ForceDirectories(Transcripts);
end;

procedure InitializeWizard;
begin
  DataPage := CreateInputDirPage(wpSelectTasks,
    '保存位置',
    '听课的录音和笔记想放在哪里？',
    '安装包会把这两个位置记到用户配置里，之后程序保存录音和 Markdown 笔记时都会用它们，' +
    '以后随时可以改。',
    False, '');
  DataPage.Add('录音保存位置（上课时录下来的音频）：');
  DataPage.Add('笔记保存位置（识别 + 翻译出来的 Markdown）：');
  DataPage.Values[0] := ExpandConstant('{userdocs}\同声传译\录音');
  DataPage.Values[1] := ExpandConstant('{userdocs}\同声传译\笔记');

  KeyPage := CreateInputQueryPage(DataPage.ID,
    '翻译服务',
    'DeepSeek API key（可以留空）',
    '填了就用 DeepSeek 翻译，质量最好；留空也能用，会自动退回免费的 Google 翻译' +
    '（大陆网络通常连不上）。以后随时可以双击「设置API密钥.bat」补上。');
  KeyPage.Add('DeepSeek API key（sk- 开头）：', False);

  if GetParam('/RECORDINGS') <> '' then
    DataPage.Values[0] := GetParam('/RECORDINGS');
  if GetParam('/TRANSCRIPTS') <> '' then
    DataPage.Values[1] := GetParam('/TRANSCRIPTS');
  if GetParam('/APIKEY') <> '' then
    KeyPage.Values[0] := GetParam('/APIKEY');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = DataPage.ID then
  begin
    if Trim(DataPage.Values[0]) = '' then
    begin
      MsgBox('请填写录音保存位置。', mbError, MB_OK);
      Result := False;
    end
    else if Trim(DataPage.Values[1]) = '' then
    begin
      MsgBox('请填写笔记保存位置。', mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = KeyPage.ID then
  begin
    if (Trim(KeyPage.Values[0]) <> '') and (Pos('sk-', KeyPage.Values[0]) <> 1)
       and (GetParam('/APIKEY') = '') then
    begin
      if MsgBox('这个 key 看起来不是 sk- 开头，确定继续吗？', mbConfirmation,
                MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteUserConfig(DataPage.Values[0], DataPage.Values[1], Trim(KeyPage.Values[0]));
end;
