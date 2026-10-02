# Installer languages

`ChineseSimplified.isl` is the Simplified-Chinese message file for Inno Setup,
taken verbatim from the official Inno Setup source repository:

    https://github.com/jrsoftware/issrc/blob/main/Files/Languages/ChineseSimplified.isl

Maintainer of the translation: Zhenghan Yang (Kira) — see the header of the file.
It is kept in the repo so `build_installer.bat` produces the same Chinese wizard
everywhere, instead of depending on which translations happen to be installed.

Inno Setup itself is not bundled: the build needs Inno Setup 6 installed
(<https://jrsoftware.org/isdl.php>).

