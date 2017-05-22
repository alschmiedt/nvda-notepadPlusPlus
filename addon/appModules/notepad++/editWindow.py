#editWindow.py
#A part of theNotepad++ addon for NVDA
#Copyright (C) 2016 Tuukka Ojala, Derek Riemer
#This file is covered by the GNU General Public License.
#See the file COPYING for more details.

import addonHandler
import config
from NVDAObjects.behaviors import EditableTextWithAutoSelectDetection
from editableText import EditableText
import api
from queueHandler import registerGeneratorObject
import speech
import textInfos
import tones
import ui
import eventHandler
import re
import unicodedata
from tokenize import tokenize, untokenize, NUMBER, STRING, NAME, OP, generate_tokens, INDENT
from io import BytesIO
from StringIO import StringIO
import sys

addonHandler.initTranslation()
class Function:
	def __init__(self, name, lineNum, parameters):
		self.name = name
		self.lineNum = lineNum
		self.parameters = parameters

# indent_level(int): num of either tabs or spaces
# block_type(string): statement keyword
# stmt_info(string): additional information about stmt i.e conditionals/function name
class BlockStmts:
	def __init__(self, indent_level, block_type, stmt_info):
		self.indent_level = indent_level
		self.block_type = block_type
		self.stmt_info = stmt_info
		self.preStmts = []
		self.block_indent = -1
	def addInfo(self,extra_info):
		self.stmt_info = extra_info
	def addPreStmt(self,pre_stmt):
		self.preStmts = pre_stmt
	def addBlockIndent(self,block_indent):
		self.block_indent = block_indent


class EditWindow(EditableTextWithAutoSelectDetection):
	"""An edit window that implements all of the scripts on the edit field for Notepad++"""
	StmtIdentifiers = ["def", "while", "if", "elif", "else", "for", "try", "with", "class", "except", "finally"]
		
	def event_loseFocus(self):
		#Hack: finding the edit field from the foreground window is unreliable, so cache it here.
		self.appModule.edit = self

	def event_gainFocus(self):
		super(EditWindow, self).event_gainFocus()
		#Hack: finding the edit field from the foreground window is unreliable. If we previously cached an object, this will clean it up, allowing it to be garbage collected.
		self.appModule.edit = None

	def initOverlayClass(self):
		#Notepad++ names the edit window "N" for some stupid reason.
		#Nuke the name, because it really doesn't matter.
		self.name = ""

	def script_goToMatchingBrace(self, gesture):
		gesture.send()
		info = self.makeTextInfo(textInfos.POSITION_CARET).copy()
		#Expand to line.
		info.expand(textInfos.UNIT_LINE)
		if info.text.strip() in ('{', '}'):
			#This line is only one brace. Not very helpful to read, lets read the previous and next line as well.
			#Move it's start back a line.
			info.move(textInfos.UNIT_LINE, -1, endPoint = "start")
			# Move it's end one line, forward.
			info.move(textInfos.UNIT_LINE, 1, endPoint = "end")
			#speak the info.
			registerGeneratorObject((speech.speakMessage(i) for i in info.text.split("\n")))
		else:
			speech.speakMessage(info.text)

	#Translators: when pressed, goes to    the matching brace in Notepad++
	script_goToMatchingBrace.__doc__ = _("Goes to the brace that matches the one under the caret")
	script_goToMatchingBrace.category = "Notepad++"

	def script_goToNextBookmark(self, gesture):
		self.speakActiveLineIfChanged(gesture)

	#Translators: Script to move to the next bookmark in Notepad++.
	script_goToNextBookmark.__doc__ = _("Goes to the next bookmark")
	script_goToNextBookmark.category = "Notepad++"

	def script_goToPreviousBookmark(self, gesture):
		self.speakActiveLineIfChanged(gesture)

	#Translators: Script to move to the next bookmark in Notepad++.
	script_goToPreviousBookmark.__doc__ = _("Goes to the previous bookmark")
	script_goToPreviousBookmark.category = "Notepad++"

	def speakActiveLineIfChanged(self, gesture):
		old = self.makeTextInfo(textInfos.POSITION_CARET)
		gesture.send()
		new = self.makeTextInfo(textInfos.POSITION_CARET)
		if new.bookmark.startOffset != old.bookmark.startOffset:
			new.expand(textInfos.UNIT_LINE)
			speech.speakMessage(new.text)

	def event_typedCharacter(self, ch):
		super(EditWindow, self).event_typedCharacter(ch)
		if not config.conf["notepadPp"]["lineLengthIndicator"]:
			return
		textInfo = self.makeTextInfo(textInfos.POSITION_CARET)
		textInfo.expand(textInfos.UNIT_LINE)
		if textInfo.bookmark.endOffset - textInfo.bookmark.startOffset >= config.conf["notepadPp"]["maxLineLength"]:
			tones.beep(500, 50)

	def script_reportLineOverflow(self, gesture):
		if self.appModule.isAutocomplete:
			gesture.send()
			return
		self.script_caret_moveByLine(gesture)
		if not config.conf["notepadPp"]["lineLengthIndicator"]:
			return
		info = self.makeTextInfo(textInfos.POSITION_CARET)
		info.expand(textInfos.UNIT_LINE)
		if len(info.text.strip('\r\n\t ')) > config.conf["notepadPp"]["maxLineLength"]:
			tones.beep(500, 50)

	def event_caret(self):
		super(EditWindow, self).event_caret()
		if not config.conf["notepadPp"]["lineLengthIndicator"]:
			return
		caretInfo = self.makeTextInfo(textInfos.POSITION_CARET)
		lineStartInfo = self.makeTextInfo(textInfos.POSITION_CARET).copy()
		caretInfo.expand(textInfos.UNIT_CHARACTER)
		lineStartInfo.expand(textInfos.UNIT_LINE)
		caretPosition = caretInfo.bookmark.startOffset -lineStartInfo.bookmark.startOffset
		#Is it not a blank line, and are we further in the line than the marker position?
		if caretPosition > config.conf["notepadPp"]["maxLineLength"] -1 and caretInfo.text not in ['\r', '\n']:
			tones.beep(500, 50)

	def script_goToFirstOverflowingCharacter(self, gesture):
		info = self.makeTextInfo(textInfos.POSITION_CARET)
		info.expand(textInfos.UNIT_LINE)
		if len(info.text) > config.conf["notepadPp"]["maxLineLength"]:
			info.move(textInfos.UNIT_CHARACTER, config.conf["notepadPp"]["maxLineLength"], "start")
			info.updateCaret()
			info.collapse()
			info.expand(textInfos.UNIT_CHARACTER)
			speech.speakMessage(info.text)

	#Translators: Script to move the cursor to the first character on the current line that exceeds the users maximum allowed line length.
	script_goToFirstOverflowingCharacter.__doc__ = _("Moves to the first character that is after the maximum line length")
	script_goToFirstOverflowingCharacter.category = "Notepad++"

	def script_reportLineInfo(self, gesture):
		ui.message(self.parent.next.next.firstChild.getChild(2).name) 


	#Translators: Script that announces information about the current line.
	script_reportLineInfo.__doc__ = _("speak the line info item on the status bar")
	script_reportLineInfo.category = "Notepad++"
	
	def getDocumentLines(self):
		lines = self.makeTextInfo(textInfos.POSITION_CARET)._getStoryText().split("\n")
		return [unicodedata.normalize('NFKD', l).encode('ascii','ignore') for l in lines]

	def refreshFunctions(self, gesture):
		strLines = self.getDocumentLines()
		functions = {}
		for idx, l in enumerate(strLines):
			funcName = re.search('(?<=def\s)\w+', l)
			if funcName != None:
				parameters = re.search('\(([^)]+)\)', l).group(0).replace("(","",3).split(",")
				function = Function(funcName.group(0), idx, parameters)
				functions[function.name] = function
		return functions

	def script_findLines(self, gesture):
		functions = self.refreshFunctions(gesture)
		ui.message("There are %d functions" % len(functions))
		for key, value in functions.items():
			ui.message(value.name)
		
	def script_functionParameters(self, gesture):
		functions = self.refreshFunctions(gesture)
		strLines = self.getDocumentLines()
		docInfo = self.parent.next.next.firstChild.getChild(2).name
		curLineNum = int(re.search("[^Ln:u'\s][0-9]*", docInfo).group(0))
		curLine = strLines[curLineNum - 1].strip()
		funcName = re.search('([a-z_][a-z0-9_]*)\($', curLine, re.IGNORECASE)
		if funcName != None:
			function = functions[funcName.group(1)]
			ui.message("Parameters for %s are" % funcName.group(1))
			for p in function.parameters:
				ui.message(p)
				
	
	def find_block(self, stmtList, curLineIndent):
		while(len(stmtList) != 0):
			stmt = stmtList.pop()
			if(stmt.indent_level < curLineIndent):
				return stmt.block_type + stmt.stmt_info
		return "You are at outer scope"
	
	def find_indent(self, string):
		if config.conf["notepadPp"]["changeToSpaces"]:
			spaces = len(string) - len(string.lstrip(' '))
		else:
			spaces = len(string) - len(string.lstrip('\t'))
		return spaces
		
	def checkSpaces(self, spacesString):
		if config.conf["notepadPp"]["changeToSpaces"]:
			if "\t" in spacesString:
				return False
		else:
			if " " in spacesString:
				return False
		return True
	
	def script_identifyBlock(self, gesture):
		stmtList = []
		strLines = self.getDocumentLines()
		docInfo = self.parent.next.next.firstChild.getChild(2).name
		curLineNum = int(re.search("[^Ln:u'\s][0-9]*", docInfo).group(0))
		curLineIndent = self.find_indent(strLines[curLineNum-1])
		for idx in range(0, curLineNum):
			currentLine = strLines[idx]
			beginningSpaces = re.search("[\t\s+]*", currentLine).group(0)
			if (self.checkSpaces(beginningSpaces)):
				if currentLine.lstrip() != "":
					firstWord = re.search("([a-z][a-z]*)", currentLine).group(0)
					if firstWord in self.StmtIdentifiers:
						if firstWord == "def":
							extraInfo = re.search("^[^\(]+", currentLine).group(0)
						else:
							extraInfo = re.search("^[^\:]+", currentLine).group(0)
							extraInfo = extraInfo.replace("(", "")
							extraInfo = extraInfo.replace(")", "")
						stmtList.append(BlockStmts(self.find_indent(currentLine), firstWord, extraInfo))
			else:
				ui.message("you have mixed spaces and tabs")
				return
		result = self.find_block(stmtList, curLineIndent)
		ui.message(result)
			
	def checkPreStmts(self,blockStmt, stmt_list):
		while(len(stmt_list)):
			curStmt = stmt_list.pop()
			if curStmt.block_type in blockStmt.preStmts and curStmt.indent_level == blockStmt.indent_level and curStmt.block_indent != -1:
				return True
			elif len(stmt_list) == 0:
				return False
			

	
	def checkLine(self,line, stmt_list):
		curIndent = self.find_indent(line)
		stmt_length = len(stmt_list)
		for idx in range(0, stmt_length):
			curStmt = stmt_list.pop()
			if curIndent > curStmt.indent_level:
				if curStmt.block_indent == -1:
					curStmt.addBlockIndent(curIndent)
					return True
				elif curStmt.block_indent == curIndent:
					return True
				else:
					return False
				break
			elif curIndent <= curStmt.indent_level and curStmt.block_indent == -1:
				return False
		return True

				  
	def script_checkIndents(self, gesture):
		stmtList = []
		strLines = self.getDocumentLines()
		docInfo = self.parent.next.next.firstChild.getChild(2).name
		curLineNum = int(re.search("[^Ln:u'\s][0-9]*", docInfo).group(0))
		for idx in range(0, curLineNum):
			line = strLines[idx]
			beginningSpaces = re.search("[\t\s+]*", line).group(0)
			if line.strip() != "":
				if self.checkSpaces(beginningSpaces):
					firstword = re.search("([a-z][a-z]*)", line).group(0)
					if firstword in self.StmtIdentifiers:
						newBlock = BlockStmts(self.find_indent(line), firstword, "")
						if firstword in ["else", "elif"]:
							newBlock.addPreStmt(["if", "elif"])
						elif firstword in ["except", "finally"]:
							newBlock.addPreStmt(["try","except"])
						else: 
							if (self.checkLine(line, list(stmtList))) != True:
								ui.message( "Error on line " + str(idx + 1))
								return
						if(len(newBlock.preStmts) != 0 and self.checkPreStmts(newBlock, list(stmtList)) != True):
							ui.message( "Error on line " + str(idx + 1))
							return
						stmtList.append(newBlock)
					else:
						newList = list(stmtList)
						if (self.checkLine(line, newList) != True):
							ui.message( "Error on line " + str(idx + 1))
							return
				else:
					ui.message("mixed spaces and tabs on line " + str(idx + 1))
					return
		ui.message( "Good Indentation")
		return

	def script_reportFindResult(self, gesture):
		old = self.makeTextInfo(textInfos.POSITION_SELECTION)
		gesture.send()
		new = self.makeTextInfo(textInfos.POSITION_SELECTION)
		if new.bookmark.startOffset != old.bookmark.startOffset:
			new.expand(textInfos.UNIT_LINE)
			speech.speakMessage(new.text)
		else:
			#Translators: Message shown when there are no more search results in this direction using the notepad++ find command.
			speech.speakMessage(_("No more search results in this direction."))
		
	#Translators: when pressed, goes to    the Next search result in Notepad++
	script_reportFindResult.__doc__ = _("Queries the next or previous search result and speaks the selection and current line of it.")
	script_reportFindResult.category = "Notepad++"
	
	__gestures = {
		"kb:control+b" : "goToMatchingBrace",
		"kb:f2": "goToNextBookmark",
		"kb:shift+f2": "goToPreviousBookmark",
		"kb:nvda+shift+\\": "reportLineInfo",
		"kb:upArrow": "reportLineOverflow",
		"kb:downArrow": "reportLineOverflow",
		"kb:nvda+g": "goToFirstOverflowingCharacter",
		"kb:f3" : "reportFindResult",
		"kb:shift+f3" : "reportFindResult",
		"kb:nvda+shift+q" : "findLines",
		"kb:nvda+shift+r" : "functionParameters",
		"kb:nvda+shift+t" : "identifyBlock",
		"kb:nvda+shift+h" : "checkIndents",
	}