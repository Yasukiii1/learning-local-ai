@echo off
REM ==================================================================
REM  Settings for the 5 student models. Edit with Notepad, then save.
REM  Used by start_students.bat and start_students_hidden.bat.
REM ==================================================================

REM Full path to llama-server.exe, for example:
REM   set "LLAMA_SERVER=C:\llama.cpp\build\bin\Release\llama-server.exe"
REM Leave it empty to use the llama-server that is on your PATH.
set "LLAMA_SERVER="

REM The model file. Leave it empty to use the .gguf file in the "models" folder
REM (download_model.bat puts it there).
set "MODEL="

REM Memory for each student (split into 2 slots of half the size).
REM   8 GB graphics card  -> 12000
REM   12 GB or more       -> 20000
set "CTX=12000"

REM How many model layers go on the graphics card. 99 = all of them (fastest).
REM If the students crash with "out of memory", try 22, then 18.
set "NGL=99"

REM CPU threads per student.
set "THREADS=3"
