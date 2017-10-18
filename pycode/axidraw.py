# axidraw.py
# Part of the AxiDraw driver for Inkscape
# https://github.com/evil-mad/AxiDraw
#
# Version 1.5.9, dated August 9, 2017.
#
# Copyright 2017 Windell H. Oskay, Evil Mad Scientist Laboratories
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
# Requires Pyserial 2.7.0 or newer. Pyserial 3.0 recommended.

import sys
sys.path.append('lib')

import inkex
from simpletransform import *
import simplepath
import math
from array import *
import gettext
import serial
import string
import time

import ebb_serial	# Requires plotink v 0.8	 https://github.com/evil-mad/plotink
import ebb_motion
import plot_utils
import axidraw_conf	#Some settings can be changed here.

try:
	xrange = xrange # We have Python 2
except:
	xrange = range # We have Python 3
try:
	basestring
except NameError:
	basestring = str

class AxiDrawClass( inkex.Effect ):

	def __init__( self ):
		inkex.Effect.__init__( self )
		self.versionString = "AxiDraw Control - Version 1.5.9, dated 2017-08-09"
		self.spewDebugdata = False
		self.debugPause = -1	# Debug method: Simulate a manual button press at a given node. Value of -1: Do not force pause.

		self.start_time = time.time()
		self.ptEstimate = 0.0	#plot time estimate

		self.OptionParser.add_option( "--mode",	action="store", type="string", dest="mode", default="plot", help="Mode (or GUI tab) selected" )
		self.OptionParser.add_option( "--penUpPosition", action="store", type="int", dest="penUpPosition", default=axidraw_conf.PenUpPos, help="Position of pen when lifted" )
		self.OptionParser.add_option( "--penDownPosition", action="store", type="int", dest="penDownPosition", default=axidraw_conf.PenDownPos, help="Position of pen for painting" )
		self.OptionParser.add_option( "--setupType", action="store", type="string", dest="setupType", default="align-mode", help="The setup option selected" )
		self.OptionParser.add_option( "--penDownSpeed", action="store", type="int", dest="penDownSpeed", default=axidraw_conf.PenDownSpeed, help="Speed (step/sec) while pen is down" )
		self.OptionParser.add_option( "--penUpSpeed", action="store", type="int", dest="penUpSpeed", default=axidraw_conf.PenUpSpeed, help="Rapid speed (percent) while pen is up" )
		self.OptionParser.add_option( "--penLiftRate", action="store", type="int", dest="penLiftRate", default=axidraw_conf.penLiftRate, help="Rate of lifting pen " )
		self.OptionParser.add_option( "--penLiftDelay", action="store", type="int", dest="penLiftDelay", default=axidraw_conf.penLiftDelay, help="Added delay after pen up (ms)" )
		self.OptionParser.add_option( "--penLowerRate", action="store", type="int", dest="penLowerRate", default=axidraw_conf.penLowerRate, help="Rate of lowering pen " )
		self.OptionParser.add_option( "--penLowerDelay", action="store", type="int", dest="penLowerDelay", default=axidraw_conf.penLowerDelay, help="Added delay after pen down (ms)" )
		self.OptionParser.add_option( "--autoRotate", action="store", type="inkbool", dest="autoRotate", default=axidraw_conf.autoRotate, help="Auto pick portrait or landscape mode" )
		self.OptionParser.add_option( "--constSpeed", action="store", type="inkbool", dest="constSpeed", default=axidraw_conf.constSpeed, help="Constant velocity when pen is down" )
		self.OptionParser.add_option( "--reportTime", action="store", type="inkbool", dest="reportTime", default=axidraw_conf.reportTime, help="Report time elapsed" )
		self.OptionParser.add_option( "--resolution", action="store", type="int", dest="resolution", default=axidraw_conf.resolution, help="Resolution factor" )
		self.OptionParser.add_option( "--smoothness", action="store", type="float", dest="smoothness", default=axidraw_conf.smoothness, help="Smoothness of curves" )
		self.OptionParser.add_option( "--cornering", action="store", type="float", dest="cornering", default=axidraw_conf.smoothness, help="Cornering speed factor" )
		self.OptionParser.add_option( "--manualType", action="store", type="string", dest="manualType", default="version-check", help="The active option when Apply was pressed" )
		self.OptionParser.add_option( "--WalkDistance", action="store", type="float", dest="WalkDistance", default=1, help="Distance for manual walk" )
		self.OptionParser.add_option( "--resumeType", action="store", type="string", dest="resumeType", default="ResumeNow", help="The active option when Apply was pressed" )
		self.OptionParser.add_option( "--layerNumber", action="store", type="int", dest="layerNumber", default=axidraw_conf.DefaultLayer, help="Selected layer for multilayer plotting" )
		self.OptionParser.add_option( "--fileOutput", action="store", type="inkbool", dest="fileOutput", default=axidraw_conf.fileOutput, help="Output new contents of SVG on stdout" )
		self.OptionParser.add_option( "--previewOnly", action="store", type="inkbool", dest="previewOnly", default=axidraw_conf.previewOnly, help="Offline preview. Simulate plotting only." )
		self.OptionParser.add_option( "--previewType", action="store", type="int", dest="previewType", default=axidraw_conf.previewType, help="Preview mode rendering" )
		self.serialPort = None
		self.penUp = None  #Initial state of pen is neither up nor down, but _unknown_.
		self.virtualPenUp = False  #Keeps track of pen postion when stepping through plot before resuming
		self.ignoreLimits = False

		fX = None
		fY = None
		self.fCurrX = axidraw_conf.StartPosX
		self.fCurrY = axidraw_conf.StartPosY
		self.ptFirst = ( axidraw_conf.StartPosX, axidraw_conf.StartPosY)
		self.bStopped = False
		self.fSpeed = 1
		self.resumeMode = False
		self.nodeCount = int( 0 )		#NOTE: python uses 32-bit ints.
		self.nodeTarget = int( 0 )
		self.pathcount = int( 0 )
		self.LayersFoundToPlot = False
		self.UseCustomLayerSpeed = False
		self.UseCustomLayerPenHeight = False
		self.LayerPenDownPosition = -1
		self.LayerPenDownSpeed = -1
		self.sCurrentLayerName = ''

		self.penUpDistSteps = 0.0
		self.penDownDistSteps = 0.0

		#Values read from file:
		self.svgLayer_Old = int( 0 )
		self.svgNodeCount_Old = int( 0 )
		self.svgDataRead_Old = False
		self.svgLastPath_Old = int( 0 )
		self.svgLastPathNC_Old = int( 0 )
		self.svgLastKnownPosX_Old = float( 0.0 )
		self.svgLastKnownPosY_Old = float( 0.0 )
		self.svgPausedPosX_Old = float( 0.0 )
		self.svgPausedPosY_Old = float( 0.0 )

		#New values to write to file:
		self.svgLayer = int( 0 )
		self.svgNodeCount = int( 0 )
		self.svgDataRead = False
		self.svgLastPath = int( 0 )
		self.svgLastPathNC = int( 0 )
		self.svgLastKnownPosX = float( 0.0 )
		self.svgLastKnownPosY = float( 0.0 )
		self.svgPausedPosX = float( 0.0 )
		self.svgPausedPosY = float( 0.0 )

		self.PrintInLayersMode = False

		self.svgWidth = 0
		self.svgHeight = 0
		self.printPortrait = False

		self.xBoundsMax = axidraw_conf.PageWidthIn
		self.xBoundsMin = axidraw_conf.StartPosX
		self.yBoundsMax = axidraw_conf.PageHeightIn
		self.yBoundsMin = axidraw_conf.StartPosY

		self.svgTransform = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

		self.stepsPerInch = 0 # must be set to a nonzero value before plotting.  Steps along native motor axis.
		self.stepsPerInchXY = self.stepsPerInch		# Steps along XY axes

		self.PenDownSpeed = axidraw_conf.PenDownSpeed * axidraw_conf.SpeedScale / 110.0 #Default XY speed when pen is down
		self.penUpSpeed = axidraw_conf.PenUpSpeed * axidraw_conf.SpeedScale / 110.0 #Default XY speed when pen is down



		self.DocUnits = "in"
		self.DocUnitScaleFactor = 1
		self.sq2 = math.sqrt(2.0)

		# So that we only generate a warning once for each
		# unsupported SVG element, we use a dictionary to track
		# which elements have received a warning
		self.warnings = {}
		self.warnOutOfBounds = False

		self.previewLayer = inkex.etree.Element(inkex.addNS( 'g', 'svg' ))
		self.previewSLD = inkex.etree.SubElement( self.previewLayer, inkex.addNS( 'g', 'svg' ) )
		self.previewSLU = inkex.etree.SubElement( self.previewLayer, inkex.addNS( 'g', 'svg' ) )
		self.pathDataPU = []	# pen-up path data for preview layers
		self.pathDataPD = []	# pen-down path data for preview layers
		self.pathDataPenUp = -1	# A value of -1 indicates an indeterminate state- requiring new "M" in path.
		self.PreviewScaleFactor = 1.0 # Allow scaling in case of non-viewbox rendering

		self.velDataPlot = False
		self.velDataTime = 0
		self.velDataChart1 = []	# Velocity visualization, for preview of velocity vs time Motor 1
		self.velDataChart2 = []	# Velocity visualization, for preview of velocity vs time Motor 2
		self.velDataChartT = []	# Velocity visualization, for preview of velocity vs time Total V

	def effect( self ):
		'''Main entry point: check to see which mode/tab is selected, and act accordingly.'''

		skipSerial = False
		if self.options.previewOnly:
			skipSerial = True

		self.options.mode = self.options.mode.strip("\"")
		self.options.setupType = self.options.setupType.strip("\"")
		self.options.manualType = self.options.manualType.strip("\"")
		self.options.resumeType = self.options.resumeType.strip("\"")

		if (self.options.mode == "Help"):
			return
		if (self.options.mode == "options"):
			return
		if (self.options.mode == "timing"):
			return
		if (self.options.mode == "version"):
			inkex.errormsg( gettext.gettext(self.versionString))
			return
		if (self.options.mode == "manual"):
			if (self.options.manualType == "none"):
				return	#No option selected. Do nothing and return no error.
			elif (self.options.manualType == "strip-data"):
				self.svg = self.document.getroot()
				for node in self.svg.xpath( '//svg:WCB', namespaces=inkex.NSS ):
					self.svg.remove( node )
				for node in self.svg.xpath( '//svg:eggbot', namespaces=inkex.NSS ):
					self.svg.remove( node )
				inkex.errormsg( gettext.gettext( "I've removed all AxiDraw data from this SVG file. Have a great day!" ) )
				return

		if skipSerial == False:
			self.serialPort = ebb_serial.openPort()
			if self.serialPort is None:
				inkex.errormsg( gettext.gettext( "Failed to connect to AxiDraw. :(" ))
				return

		self.svg = self.document.getroot()
		self.CheckSVGforWCBData()
		useOldResumeData = True

		if self.options.mode == "plot":
			self.LayersFoundToPlot = False
			useOldResumeData = False
			self.PrintInLayersMode = False
			self.plotCurrentLayer = True
			self.svgNodeCount = 0
			self.svgLastPath = 0
			self.svgLayer = 12345  # indicate (to resume routine) that we are plotting all layers.
			self.plotDocument()

		elif self.options.mode == "resume":
			useOldResumeData = False
			self.resumePlotSetup()
			if self.resumeMode:
				self.plotDocument()
			elif ( self.options.resumeType == "justGoHome" ):
				self.plotDocument()
				self.svgNodeCount = self.svgNodeCount_Old	# New values to write to file:
				self.svgLastPath = self.svgLastPath_Old
				self.svgLastPathNC = self.svgLastPathNC_Old
				self.svgPausedPosX = self.svgPausedPosX_Old
				self.svgPausedPosY = self.svgPausedPosY_Old
				self.svgLayer = self.svgLayer_Old
			else:
				inkex.errormsg( gettext.gettext( "There does not seem to be any in-progress plot to resume." ))

		elif self.options.mode == "layers":
			useOldResumeData = False
			self.PrintInLayersMode = True
			self.plotCurrentLayer = False
			self.LayersFoundToPlot = False
			self.svgLastPath = 0
			self.svgNodeCount = 0
			self.svgLayer = self.options.layerNumber
			self.plotDocument()

		elif self.options.mode == "setup":
			useOldResumeData = True
			self.setupCommand()

		elif self.options.mode == "manual":
			useOldResumeData = True
			self.manualCommand()

		if not (useOldResumeData):
			self.svgDataRead = False
			self.UpdateSVGWCBData( self.svg )
		if self.serialPort is not None:
			if not ((self.options.mode == "manual") and (self.options.manualType == "bootload")):
				ebb_motion.doTimedPause(self.serialPort, 10) #Pause a moment for underway commands to finish...
			ebb_serial.closePort(self.serialPort)

	def resumePlotSetup( self ):

		self.LayerFound = False
		if ( self.svgLayer_Old < 101 ) and ( self.svgLayer_Old >= 0 ):
			self.options.layerNumber = self.svgLayer_Old
			self.PrintInLayersMode = True
			self.plotCurrentLayer = False
			self.LayerFound = True
		elif ( self.svgLayer_Old == 12345 ):  # Plot all layers
			self.PrintInLayersMode = False
			self.plotCurrentLayer = True
			self.LayerFound = True
		if ( self.LayerFound ):
			if ( self.svgNodeCount_Old > 0 ):
				self.nodeTarget = self.svgNodeCount_Old
				self.svgLayer = self.svgLayer_Old
				self.ServoSetup()
				self.penRaise()
				self.EnableMotors() #Set plotting resolution
				if self.options.resumeType == "ResumeNow":
					self.resumeMode = True
				self.fSpeed = self.PenDownSpeed
				self.fCurrX = self.svgLastKnownPosX_Old + axidraw_conf.StartPosX
				self.fCurrY = self.svgLastKnownPosY_Old + axidraw_conf.StartPosY
				if self.spewDebugdata:
					inkex.errormsg( 'Entering resume mode at layer:  ' + str(self.svgLayer) )

	def CheckSVGforWCBData( self ):
		self.svgDataRead = False
		self.recursiveWCBDataScan( self.svg )
		if self.options.fileOutput:
			if ( not self.svgDataRead ): #if there is no WCB data, add some:
				WCBlayer = inkex.etree.SubElement( self.svg, 'WCB' )
				WCBlayer.set( 'layer', str( 0 ) )
				WCBlayer.set( 'node', str( 0 ) )			#node paused at, if saved in paused state
				WCBlayer.set( 'lastpath', str( 0 ) )		#Last path number that has been fully painted
				WCBlayer.set( 'lastpathnc', str( 0 ) )		#Node count as of finishing last path.
				WCBlayer.set( 'lastknownposx', str( 0 ) )  #Last known position of carriage
				WCBlayer.set( 'lastknownposy', str( 0 ) )
				WCBlayer.set( 'pausedposx', str( 0 ) )	   #The position of the carriage when "pause" was pressed.
				WCBlayer.set( 'pausedposy', str( 0 ) )

	def recursiveWCBDataScan( self, aNodeList ):
		if ( not self.svgDataRead ):
			for node in aNodeList:
				if node.tag == 'svg':
					self.recursiveWCBDataScan( node )
				elif node.tag == inkex.addNS( 'WCB', 'svg' ) or node.tag == 'WCB':
					try:
						self.svgLayer_Old = int( node.get( 'layer' ) )
						self.svgNodeCount_Old = int( node.get( 'node' ) )
						self.svgLastPath_Old = int( node.get( 'lastpath' ) )
						self.svgLastPathNC_Old = int( node.get( 'lastpathnc' ) )
						self.svgLastKnownPosX_Old = float( node.get( 'lastknownposx' ) )
						self.svgLastKnownPosY_Old = float( node.get( 'lastknownposy' ) )
						self.svgPausedPosX_Old = float( node.get( 'pausedposx' ) )
						self.svgPausedPosY_Old = float( node.get( 'pausedposy' ) )
						self.svgDataRead = True
					except:
						pass

	def UpdateSVGWCBData( self, aNodeList ):
		if self.options.fileOutput:
			if ( not self.svgDataRead ):
				for node in aNodeList:
					if node.tag == 'svg':
						self.UpdateSVGWCBData( node )
					elif node.tag == inkex.addNS( 'WCB', 'svg' ) or node.tag == 'WCB':
						node.set( 'layer', str( self.svgLayer ) )
						node.set( 'node', str( self.svgNodeCount ) )
						node.set( 'lastpath', str( self.svgLastPath ) )
						node.set( 'lastpathnc', str( self.svgLastPathNC ) )
						node.set( 'lastknownposx', str( (self.svgLastKnownPosX ) ) )
						node.set( 'lastknownposy', str( (self.svgLastKnownPosY ) ) )
						node.set( 'pausedposx', str( (self.svgPausedPosX) ) )
						node.set( 'pausedposy', str( (self.svgPausedPosY) ) )
						self.svgDataRead = True

	def setupCommand( self ):
		"""Execute commands from the "setup" mode"""

		if self.serialPort is None:
			return

		self.ServoSetupWrapper()

		if self.options.setupType == "align-mode":
			self.penRaise()
			ebb_motion.sendDisableMotors(self.serialPort)

		elif self.options.setupType == "toggle-pen":
			ebb_motion.TogglePen(self.serialPort)

	def manualCommand( self ):
		"""Execute commands in the "manual" mode/tab"""

		if self.serialPort is None:
			return

		if self.options.manualType == "raise-pen":
			self.ServoSetupWrapper()
			self.penRaise()

		elif self.options.manualType == "lower-pen":
			self.ServoSetupWrapper()
			self.penLower()

		elif self.options.manualType == "enable-motors":
			self.EnableMotors()

		elif self.options.manualType == "disable-motors":
			ebb_motion.sendDisableMotors(self.serialPort)

		elif self.options.manualType == "version-check":
			strVersion = ebb_serial.queryVersion( self.serialPort)
			inkex.errormsg( 'I asked the EBB for its version info, and it replied:\n ' + strVersion )

		elif self.options.manualType == "bootload":
			ebb_serial.bootload(self.serialPort)
			inkex.errormsg( gettext.gettext( "Entering bootloader mode for firmware programming.\n" +
			"To resume normal operation, you will need to first\n" +
			"disconnect the AxiDraw from both USB and power." ) )

		else:  # self.options.manualType is walk motor:
			if self.options.manualType == "walk-y-motor":
				nDeltaX = 0
				nDeltaY = self.options.WalkDistance
			elif self.options.manualType == "walk-x-motor":
				nDeltaY = 0
				nDeltaX = self.options.WalkDistance
			else:
				return

			self.fSpeed = self.PenDownSpeed

			self.EnableMotors() #Set plotting resolution
			self.fCurrX = self.svgLastKnownPosX_Old + axidraw_conf.StartPosX
			self.fCurrY = self.svgLastKnownPosY_Old + axidraw_conf.StartPosY
			self.ignoreLimits = True
			fX = self.fCurrX + nDeltaX   # Note: Walking motors is strictly relative to initial position.
			fY = self.fCurrY + nDeltaY   #       New position is not saved, and may interfere with (e.g.,) resuming plots.
			self.plotSegmentWithVelocity( fX, fY, 0, 0)

	def updateVCharts( self, v1, v2, vT):
		#Update velocity charts, using some appropriate scaling for X and Y display.
		tempTime = self.DocUnitScaleFactor * self.velDataTime/1000.0
		self.velDataChart1.append(" %0.3f %0.3f" % (tempTime, 8.5 - self.DocUnitScaleFactor * v1/10.0) )
		self.velDataChart2.append(" %0.3f %0.3f" % (tempTime, 8.5 - self.DocUnitScaleFactor * v2/10.0) )
		self.velDataChartT.append(" %0.3f %0.3f" % (tempTime, 8.5 - self.DocUnitScaleFactor * vT/10.0) )

	def vChartMoveTo( self):
		#Use a moveto statement
		self.velDataChart1.append("M")
		self.velDataChart2.append("M")
		self.velDataChartT.append("M")


	def plotDocument( self ):
		# Plot the actual SVG document, if so selected in the interface
		# parse the svg data as a series of line segments and send each segment to be plotted

		if (not self.getDocProps()):
			# Error: This document appears to have inappropriate (or missing) dimensions.
			inkex.errormsg( gettext.gettext('This document does not have valid dimensions.\r'))
			inkex.errormsg( gettext.gettext('The document dimensions must be in either millimeters (mm) or inches (in).\r\r'))
			inkex.errormsg( gettext.gettext('Consider starting with the Letter landscape or '))
			inkex.errormsg( gettext.gettext('the A4 landscape template.\r\r'))
			inkex.errormsg( gettext.gettext('Document dimensions may also be set in Inkscape,\r'))
			inkex.errormsg( gettext.gettext('using File > Document Properties.'))
			return

		self.DocUnits = self.getDocumentUnit()
		userUnitsWidth = plot_utils.unitsToUserUnits("1in")
		self.DocUnitScaleFactor = plot_utils.userUnitToUnits(userUnitsWidth, self.DocUnits)

		if not self.options.previewOnly:
			self.options.previewType = 0	# Only render previews if we are in preview mode.
			velDataPlot = False
			if self.serialPort is None:
				return
			unused = ebb_motion.QueryPRGButton(self.serialPort)	#Initialize button-press detection

		if self.options.previewOnly:
			# Remove old preview layers, whenever preview mode is enabled
			for node in self.svg:
				if node.tag == inkex.addNS( 'g', 'svg' ) or node.tag == 'g':
					if ( node.get( inkex.addNS( 'groupmode', 'inkscape' ) ) == 'layer' ):
						LayerName = node.get( inkex.addNS( 'label', 'inkscape' ) )
						if LayerName == '% Preview':
							self.svg.remove( node )

			self.previewLayer.set( inkex.addNS('groupmode', 'inkscape' ), 'layer' )
			self.previewLayer.set( inkex.addNS( 'label', 'inkscape' ), '% Preview' )
			self.previewSLD.set( inkex.addNS('groupmode', 'inkscape' ), 'layer' )
			self.previewSLD.set( inkex.addNS( 'label', 'inkscape' ), '% Pen-down drawing' )
			self.previewSLU.set( inkex.addNS('groupmode', 'inkscape' ), 'layer' )
			self.previewSLU.set( inkex.addNS( 'label', 'inkscape' ), '% Pen-up transit' )
			self.svg.append( self.previewLayer )

		if self.options.mode == "resume":
			if self.resumeMode:
				fX = self.svgPausedPosX_Old + axidraw_conf.StartPosX
				fY = self.svgPausedPosY_Old + axidraw_conf.StartPosY
				self.resumeMode = False
				self.plotSegmentWithVelocity(fX, fY, 0, 0) # pen-up move to starting point
				self.resumeMode = True
				self.nodeCount = 0
			elif ( self.options.resumeType == "justGoHome" ):
				fX = axidraw_conf.StartPosX
				fY = axidraw_conf.StartPosY
				self.plotSegmentWithVelocity(fX, fY, 0, 0)
				return

		# Viewbox handling
		# Ignores translations and the preserveAspectRatio attribute

		viewbox = self.svg.get( 'viewBox' )
		if viewbox:
			vinfo = viewbox.strip().replace( ',', ' ' ).split( ' ' )
			Offset0 = -float(vinfo[0])
			Offset1 = -float(vinfo[1])
			if ( vinfo[2] != 0 ) and ( vinfo[3] != 0 ):
				# TODO: Handle a wide range of viewBox formats and values
				sx = self.svgWidth / float( vinfo[2] )
				sy = self.svgHeight / float( vinfo[3] )
				self.DocUnitScaleFactor = 1.0 / sx # Scale preview to viewbox

		else:
			# Handle case of no viewbox provided.
			sx = 1.0 / float( plot_utils.pxPerInch)
			sy = sx
			Offset0 = 0.0
			Offset1 = 0.0

		self.svgTransform = parseTransform( 'scale(%f,%f) translate(%f,%f)' % (sx, sy,Offset0, Offset1))

		self.ServoSetup()
		self.penRaise()
		self.EnableMotors() #Set plotting resolution

		try:
			# wrap everything in a try so we can for sure close the serial port
			self.recursivelyTraverseSvg( self.svg, self.svgTransform )
			self.penRaise()   #Always end with pen-up

			# return to home after end of normal plot
			if ( ( not self.bStopped ) and ( self.ptFirst ) ):
				self.xBoundsMin = axidraw_conf.StartPosX
				self.yBoundsMin = axidraw_conf.StartPosY
				fX = self.ptFirst[0]
				fY = self.ptFirst[1]
				self.nodeCount = self.nodeTarget
				self.plotSegmentWithVelocity( fX, fY, 0, 0)

			if ( not self.bStopped ):
				if (self.options.mode == "plot") or (self.options.mode == "layers") or (self.options.mode == "resume"):
					self.svgLayer = 0
					self.svgNodeCount = 0
					self.svgLastPath = 0
					self.svgLastPathNC = 0
					self.svgLastKnownPosX = 0
					self.svgLastKnownPosY = 0
					self.svgPausedPosX = 0
					self.svgPausedPosY = 0
					#Clear saved position data from the SVG file,
					#  IF we have completed a normal plot from the plot, layer, or resume mode.
			if (self.warnOutOfBounds):
				inkex.errormsg( gettext.gettext( 'Warning: AxiDraw movement was limited by its physical range of motion. If everything looks right, your document may have an error with its units or scaling. Contact technical support for help!' ) )

			if (self.options.previewType > 0): # Render preview. Only possible when in preview mode.
				strokeWidth = "0.2mm"	# Adjust this here, in your preferred units.
				userUnitsWidth = self.unittouu(strokeWidth)
				strokeWidthConverted = self.uutounit(userUnitsWidth, self.DocUnits)
				nsPrefix = "plot"
				if (self.options.previewType > 1):
					style = { 'stroke': 'blue', 'stroke-width': strokeWidthConverted, 'fill': 'none' } #Pen-up: blue
					path_attrs = {
						'style': simplestyle.formatStyle( style ),
						'd': " ".join(self.pathDataPU),
						inkex.addNS( 'desc', nsPrefix ): "pen-up transit" }
					PUpath = inkex.etree.SubElement( self.previewSLU,
						inkex.addNS( 'path', 'svg '), path_attrs, nsmap=inkex.NSS )

				if ((self.options.previewType == 1) or (self.options.previewType == 3)):
					style = { 'stroke': 'red', 'stroke-width': strokeWidthConverted, 'fill': 'none' } #Pen-down: red
					path_attrs = {
						'style': simplestyle.formatStyle( style ),
						'd': " ".join(self.pathDataPD),
						inkex.addNS( 'desc', nsPrefix ): "pen-down drawing" }
					PDpath = inkex.etree.SubElement( self.previewSLD,
						inkex.addNS( 'path', 'svg '), path_attrs, nsmap=inkex.NSS )

				if ((self.options.previewType > 0) and self.velDataPlot):	# Preview enabled & do velocity Plot
					self.velDataChart1.insert(0, "M")
					self.velDataChart2.insert(0, "M")
					self.velDataChartT.insert(0, "M")

					style = { 'stroke': 'black', 'stroke-width': strokeWidthConverted, 'fill': 'none' }
					path_attrs = {
						'style': simplestyle.formatStyle( style ),
						'd': " ".join(self.velDataChartT),
						inkex.addNS( 'desc', nsPrefix ): "Total V" }
					PDpath = inkex.etree.SubElement(self.previewLayer,
						inkex.addNS( 'path', 'svg '), path_attrs, nsmap=inkex.NSS )

					style = { 'stroke': 'red', 'stroke-width': strokeWidthConverted, 'fill': 'none' }
					path_attrs = {
						'style': simplestyle.formatStyle( style ),
						'd': " ".join(self.velDataChart1),
						inkex.addNS( 'desc', nsPrefix ): "Motor 1 V" }
					PDpath = inkex.etree.SubElement(self.previewLayer,
						inkex.addNS( 'path', 'svg '), path_attrs, nsmap=inkex.NSS )

					style = { 'stroke': 'green', 'stroke-width': strokeWidthConverted, 'fill': 'none' }
					path_attrs = {
						'style': simplestyle.formatStyle( style ),
						'd': " ".join(self.velDataChart2),
						inkex.addNS( 'desc', nsPrefix ): "Motor 2 V" }
					PDpath = inkex.etree.SubElement(self.previewLayer,
						inkex.addNS( 'path', 'svg '), path_attrs, nsmap=inkex.NSS )

			if (self.options.reportTime):
				if self.options.previewOnly:
					m, s = divmod(self.ptEstimate/1000.0, 60)
					h, m = divmod(m, 60)
					if (h > 0):
						inkex.errormsg("Estimated print time: %d:%02d:%02d" % (h, m, s) + " (Hours, minutes, seconds)")
					else:
						inkex.errormsg("Estimated print time: %02d:%02d" % (m, s) + " (minutes, seconds)")

				elapsed_time = time.time() - self.start_time
				m, s = divmod(elapsed_time, 60)
				h, m = divmod(m, 60)
				downDist = 0.0254 * self.penDownDistSteps / (self.stepsPerInch)
				totDist = downDist + (0.0254 * self.penUpDistSteps / (self.stepsPerInch))
				if self.options.previewOnly:
					inkex.errormsg("Length of path to draw: %1.2f m." % downDist)
					inkex.errormsg("Total movement distance: %1.2f m." % totDist)
					if (self.options.previewType > 0):
						inkex.errormsg("This estimate took: %d:%02d:%02d" % (h, m, s) + " (Hours, minutes, seconds)")
				else:
					if (h > 0):
						inkex.errormsg("Elapsed time: %d:%02d:%02d" % (h, m, s) + " (Hours, minutes, seconds)")
					else:
						inkex.errormsg("Elapsed time: %02d:%02d" % (m, s) + " (minutes, seconds)")
					inkex.errormsg("Length of path drawn: %1.2f m." % downDist)
					inkex.errormsg("Total distance moved: %1.2f m." % totDist)

		finally:
			# We may have had an exception and lost the serial port...
			pass

	def recursivelyTraverseSvg( self, aNodeList,
			matCurrent=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
			parent_visibility='visible' ):
		"""
		Recursively traverse the svg file to plot out all of the
		paths.  The function keeps track of the composite transformation
		that should be applied to each path.

		This function handles path, group, line, rect, polyline, polygon,
		circle, ellipse and use (clone) elements.  Notable elements not
		handled include text.  Unhandled elements should be converted to
		paths in Inkscape.
		"""

		for node in aNodeList:
			if self.bStopped:
				return
			v = node.get( 'visibility', parent_visibility )			# Ignore invisible nodes
			if v == 'inherit':
				v = parent_visibility
			if v == 'hidden' or v == 'collapse':
				continue

			# first apply the current matrix transform to this node's transform
			matNew = composeTransform( matCurrent, parseTransform( node.get( "transform" ) ) )

			if node.tag == inkex.addNS( 'g', 'svg' ) or node.tag == 'g':

				# Store old layer status variables before recursively traversing the layer that we just found.
				oldUseCustomLayerPenHeight = self.UseCustomLayerPenHeight	# A Boolean
				oldUseCustomLayerSpeed	= self.UseCustomLayerSpeed			# A Boolean
				oldLayerPenDownPosition = self.LayerPenDownPosition			# Numeric value
				oldLayerPenDownSpeed 	= self.LayerPenDownSpeed			# Numeric value

				oldplotCurrentLayer = self.plotCurrentLayer
				oldLayerName = self.sCurrentLayerName

				if ( node.get( inkex.addNS( 'groupmode', 'inkscape' ) ) == 'layer' ):
					self.sCurrentLayerName = node.get( inkex.addNS( 'label', 'inkscape' ) )
					self.DoWePlotLayer(self.sCurrentLayerName )
					self.penRaise()
				self.recursivelyTraverseSvg( node, matNew, parent_visibility=v )

				# Restore old layer status variables
				self.UseCustomLayerPenHeight = oldUseCustomLayerPenHeight
				self.UseCustomLayerSpeed = oldUseCustomLayerSpeed

				if (self.LayerPenDownSpeed != oldLayerPenDownSpeed):
					self.LayerPenDownSpeed = oldLayerPenDownSpeed
					self.EnableMotors()	#Set speed value variables for this layer.

				if (self.LayerPenDownPosition != oldLayerPenDownPosition):
					self.LayerPenDownPosition = oldLayerPenDownPosition
					self.ServoSetup()	#Set pen height value variables for this layer.

				self.plotCurrentLayer = oldplotCurrentLayer
				self.sCurrentLayerName = oldLayerName	# Recall saved layer name after plotting deeper layer


			elif node.tag == inkex.addNS( 'use', 'svg' ) or node.tag == 'use':

				# A <use> element refers to another SVG element via an xlink:href="#blah"
				# attribute.  We will handle the element by doing an XPath search through
				# the document, looking for the element with the matching id="blah"
				# attribute.  We then recursively process that element after applying
				# any necessary (x,y) translation.
				#
				# Notes:
				#  1. We ignore the height and width attributes as they do not apply to
				#     path-like elements, and
				#  2. Even if the use element has visibility="hidden", SVG still calls
				#     for processing the referenced element.  The referenced element is
				#     hidden only if its visibility is "inherit" or "hidden".
				#  3. We may be able to unlink clones using the code in pathmodifier.py

				refid = node.get( inkex.addNS( 'href', 'xlink' ) )
				if refid:
					# [1:] to ignore leading '#' in reference
					path = '//*[@id="%s"]' % refid[1:]
					refnode = node.xpath( path )
					if refnode:
						x = float( node.get( 'x', '0' ) )
						y = float( node.get( 'y', '0' ) )
						# Note: the transform has already been applied
						if ( x != 0 ) or (y != 0 ):
							matNew2 = composeTransform( matNew, parseTransform( 'translate(%f,%f)' % (x,y) ) )
						else:
							matNew2 = matNew
						v = node.get( 'visibility', v )
						self.recursivelyTraverseSvg( refnode, matNew2, parent_visibility=v )
					else:
						continue
				else:
					continue
			elif self.plotCurrentLayer:	#Skip subsequent tag checks unless we are plotting this layer.
				if node.tag == inkex.addNS( 'path', 'svg' ):

					# If in resume mode AND self.pathcount < self.svgLastPath, then skip this path.
					# If in resume mode and self.pathcount = self.svgLastPath, then start here, and set
					# self.nodeCount equal to self.svgLastPathNC

					doWePlotThisPath = False
					if (self.resumeMode):
						if (self.pathcount < self.svgLastPath_Old ): # Fully plotted; skip.
							self.pathcount += 1
						elif (self.pathcount == self.svgLastPath_Old ): # First partially-plotted path
							self.nodeCount =  self.svgLastPathNC_Old	# nodeCount after last completed path
							doWePlotThisPath = True
					else:
						doWePlotThisPath = True
					if (doWePlotThisPath):
						self.pathcount += 1
						self.plotPath( node, matNew )

				elif node.tag == inkex.addNS( 'rect', 'svg' ) or node.tag == 'rect':

					# Manually transform
					#    <rect x="X" y="Y" width="W" height="H"/>
					# into
					#    <path d="MX,Y lW,0 l0,H l-W,0 z"/>
					# I.e., explicitly draw three sides of the rectangle and the
					# fourth side implicitly
					#
					# If in resume mode AND self.pathcount < self.svgLastPath, then skip this path.
					# If in resume mode and self.pathcount = self.svgLastPath, then start here, and set
					# self.nodeCount equal to self.svgLastPathNC

					doWePlotThisPath = False
					if (self.resumeMode):
						if (self.pathcount < self.svgLastPath_Old ): # Fully plotted; skip.
							self.pathcount += 1
						elif (self.pathcount == self.svgLastPath_Old ): # First partially-plotted path
							self.nodeCount =  self.svgLastPathNC_Old	# nodeCount after last completed path
							doWePlotThisPath = True
					else:
						doWePlotThisPath = True
					if (doWePlotThisPath):
						self.pathcount += 1
						# Create a path with the outline of the rectangle
						newpath = inkex.etree.Element( inkex.addNS( 'path', 'svg' ) )
						x = float( node.get( 'x' ) )
						y = float( node.get( 'y' ) )
						w = float( node.get( 'width' ) )
						h = float( node.get( 'height' ) )
						s = node.get( 'style' )
						if s:
							newpath.set( 'style', s )
						t = node.get( 'transform' )
						if t:
							newpath.set( 'transform', t )
						a = []
						a.append( ['M ', [x, y]] )
						a.append( [' l ', [w, 0]] )
						a.append( [' l ', [0, h]] )
						a.append( [' l ', [-w, 0]] )
						a.append( [' Z', []] )
						newpath.set( 'd', simplepath.formatPath( a ) )
						self.plotPath( newpath, matNew )

				elif node.tag == inkex.addNS( 'line', 'svg' ) or node.tag == 'line':

					# Convert
					#   <line x1="X1" y1="Y1" x2="X2" y2="Y2/>
					# to
					#   <path d="MX1,Y1 LX2,Y2"/>

					# If in resume mode AND self.pathcount < self.svgLastPath, then skip this path.
					# If in resume mode and self.pathcount = self.svgLastPath, then start here, and set
					# self.nodeCount equal to self.svgLastPathNC

					doWePlotThisPath = False
					if (self.resumeMode):
						if (self.pathcount < self.svgLastPath_Old ): # Fully plotted; skip.
							self.pathcount += 1
						elif (self.pathcount == self.svgLastPath_Old ): # First partially-plotted path
							self.nodeCount =  self.svgLastPathNC_Old	# nodeCount after last completed path
							doWePlotThisPath = True
					else:
						doWePlotThisPath = True
					if (doWePlotThisPath):
						self.pathcount += 1
						# Create a path to contain the line
						newpath = inkex.etree.Element( inkex.addNS( 'path', 'svg' ) )
						x1 = float( node.get( 'x1' ) )
						y1 = float( node.get( 'y1' ) )
						x2 = float( node.get( 'x2' ) )
						y2 = float( node.get( 'y2' ) )
						s = node.get( 'style' )
						if s:
							newpath.set( 'style', s )
						t = node.get( 'transform' )
						if t:
							newpath.set( 'transform', t )
						a = []
						a.append( ['M ', [x1, y1]] )
						a.append( [' L ', [x2, y2]] )
						newpath.set( 'd', simplepath.formatPath( a ) )
						self.plotPath( newpath, matNew )

				elif node.tag == inkex.addNS( 'polyline', 'svg' ) or node.tag == 'polyline':

					# Convert
					#  <polyline points="x1,y1 x2,y2 x3,y3 [...]"/>
					# to
					#   <path d="Mx1,y1 Lx2,y2 Lx3,y3 [...]"/>
					# Note: we ignore polylines with no points

					pl = node.get( 'points', '' ).strip()
					if pl == '':
						continue

					#if we're in resume mode AND self.pathcount < self.svgLastPath, then skip over this path.
					#if we're in resume mode and self.pathcount = self.svgLastPath, then start here, and set
					# self.nodeCount equal to self.svgLastPathNC

					doWePlotThisPath = False
					if (self.resumeMode):
						if (self.pathcount < self.svgLastPath_Old ): # Fully plotted; skip.
							self.pathcount += 1
						elif (self.pathcount == self.svgLastPath_Old ): # First partially-plotted path
							self.nodeCount =  self.svgLastPathNC_Old	# nodeCount after last completed path
							doWePlotThisPath = True
					else:
						doWePlotThisPath = True
					if (doWePlotThisPath):
						self.pathcount += 1
						pa = pl.split()
						if not len( pa ):
							continue
						d = "M " + pa[0]
						for i in range( 1, len( pa ) ):
							d += " L " + pa[i]
						newpath = inkex.etree.Element( inkex.addNS( 'path', 'svg' ) )
						newpath.set( 'd', d )
						s = node.get( 'style' )
						if s:
							newpath.set( 'style', s )
						t = node.get( 'transform' )
						if t:
							newpath.set( 'transform', t )
						self.plotPath( newpath, matNew )

				elif node.tag == inkex.addNS( 'polygon', 'svg' ) or node.tag == 'polygon':

					# Convert
					#  <polygon points="x1,y1 x2,y2 x3,y3 [...]"/>
					# to
					#   <path d="Mx1,y1 Lx2,y2 Lx3,y3 [...] Z"/>
					# Note: we ignore polygons with no points

					pl = node.get( 'points', '' ).strip()
					if pl == '':
						continue

					#if we're in resume mode AND self.pathcount < self.svgLastPath, then skip over this path.
					#if we're in resume mode and self.pathcount = self.svgLastPath, then start here, and set
					#	self.nodeCount equal to self.svgLastPathNC

					doWePlotThisPath = False
					if (self.resumeMode):
						if (self.pathcount < self.svgLastPath_Old ): # Fully plotted; skip.
							self.pathcount += 1
						elif (self.pathcount == self.svgLastPath_Old ): # First partially-plotted path
							self.nodeCount =  self.svgLastPathNC_Old	# nodeCount after last completed path
							doWePlotThisPath = True
					else:
						doWePlotThisPath = True
					if (doWePlotThisPath):
						self.pathcount += 1
						pa = pl.split()
						if not len( pa ):
							continue # skip the following statements
						d = "M " + pa[0]
						for i in xrange( 1, len( pa ) ):
							d += " L " + pa[i]
						d += " Z"
						newpath = inkex.etree.Element( inkex.addNS( 'path', 'svg' ) )
						newpath.set( 'd', d )
						s = node.get( 'style' )
						if s:
							newpath.set( 'style', s )
						t = node.get( 'transform' )
						if t:
							newpath.set( 'transform', t )
						self.plotPath( newpath, matNew )

				elif node.tag == inkex.addNS( 'ellipse', 'svg' ) or \
					node.tag == 'ellipse' or \
					node.tag == inkex.addNS( 'circle', 'svg' ) or \
					node.tag == 'circle':

						# Convert circles and ellipses to a path with two 180 degree arcs.
						# In general (an ellipse), we convert
						#   <ellipse rx="RX" ry="RY" cx="X" cy="Y"/>
						# to
						#   <path d="MX1,CY A RX,RY 0 1 0 X2,CY A RX,RY 0 1 0 X1,CY"/>
						# where
						#   X1 = CX - RX
						#   X2 = CX + RX
						# Note: ellipses or circles with a radius attribute of value 0 are ignored

						if node.tag == inkex.addNS( 'ellipse', 'svg' ) or node.tag == 'ellipse':
							rx = float( node.get( 'rx', '0' ) )
							ry = float( node.get( 'ry', '0' ) )
						else:
							rx = float( node.get( 'r', '0' ) )
							ry = rx
						if rx == 0 or ry == 0:
							continue

						#if we're in resume mode AND self.pathcount < self.svgLastPath, then skip over this path.
						#if we're in resume mode and self.pathcount = self.svgLastPath, then start here, and set
						#	self.nodeCount equal to self.svgLastPathNC

						doWePlotThisPath = False
						if (self.resumeMode):
							if (self.pathcount < self.svgLastPath_Old ):
								#This path was *completely plotted* already; skip.
								self.pathcount += 1
							elif (self.pathcount == self.svgLastPath_Old ):
								#this path is the first *not completely* plotted path:
								self.nodeCount =  self.svgLastPathNC_Old	# nodeCount after last completed path
								doWePlotThisPath = True
						else:
							doWePlotThisPath = True
						if (doWePlotThisPath):
							self.pathcount += 1

							cx = float( node.get( 'cx', '0' ) )
							cy = float( node.get( 'cy', '0' ) )
							x1 = cx - rx
							x2 = cx + rx
							d = 'M %f,%f ' % ( x1, cy ) + \
								'A %f,%f ' % ( rx, ry ) + \
								'0 1 0 %f,%f ' % ( x2, cy ) + \
								'A %f,%f ' % ( rx, ry ) + \
								'0 1 0 %f,%f' % ( x1, cy )
							newpath = inkex.etree.Element( inkex.addNS( 'path', 'svg' ) )
							newpath.set( 'd', d )
							s = node.get( 'style' )
							if s:
								newpath.set( 'style', s )
							t = node.get( 'transform' )
							if t:
								newpath.set( 'transform', t )
							self.plotPath( newpath, matNew )

				elif node.tag == inkex.addNS( 'metadata', 'svg' ) or node.tag == 'metadata':
					continue
				elif node.tag == inkex.addNS( 'defs', 'svg' ) or node.tag == 'defs':
					continue
				elif node.tag == inkex.addNS( 'namedview', 'sodipodi' ) or node.tag == 'namedview':
					continue
				elif node.tag == inkex.addNS( 'WCB', 'svg' ) or node.tag == 'WCB':
					continue
				elif node.tag == inkex.addNS( 'eggbot', 'svg' ) or node.tag == 'eggbot':
					continue
				elif node.tag == inkex.addNS( 'title', 'svg' ) or node.tag == 'title':
					continue
				elif node.tag == inkex.addNS( 'desc', 'svg' ) or node.tag == 'desc':
					continue
				elif (node.tag == inkex.addNS( 'text', 'svg' ) or node.tag == 'text' or
					node.tag == inkex.addNS( 'flowRoot', 'svg' ) or node.tag == 'flowRoot'):
					if ('text' not in self.warnings) and (self.plotCurrentLayer):
						if (self.sCurrentLayerName == ''):
							tempText = '.'
						else:
							tempText = ', found in a \nlayer named: "' + self.sCurrentLayerName + '" .'
						inkex.errormsg( gettext.gettext( 'Note: This file contains some plain text' + tempText))
						inkex.errormsg( gettext.gettext( 'Please convert your text into paths before drawing,'))
						inkex.errormsg( gettext.gettext( 'using Path > Object to Path. '))
						inkex.errormsg( gettext.gettext( 'You can also create new text by using Hershey Text,' ))
						inkex.errormsg( gettext.gettext( 'located in the menu at Extensions > Render.' ))
						self.warnings['text'] = 1
					continue
				elif node.tag == inkex.addNS( 'image', 'svg' ) or node.tag == 'image':
					if ('image' not in self.warnings) and (self.plotCurrentLayer):
						if (self.sCurrentLayerName == ''):
							tempText = ''
						else:
							tempText = ' in layer "' + self.sCurrentLayerName + '"'
						inkex.errormsg( gettext.gettext( 'Warning:' + tempText))
						inkex.errormsg( gettext.gettext( 'unable to draw bitmap images; ' ))
						inkex.errormsg( gettext.gettext( 'Please convert images to line art before drawing. ' ))
						inkex.errormsg( gettext.gettext( 'Consider using the Path > Trace bitmap tool. ' ))
						self.warnings['image'] = 1
					continue
				elif node.tag == inkex.addNS( 'pattern', 'svg' ) or node.tag == 'pattern':
					continue
				elif node.tag == inkex.addNS( 'radialGradient', 'svg' ) or node.tag == 'radialGradient':
					# Similar to pattern
					continue
				elif node.tag == inkex.addNS( 'linearGradient', 'svg' ) or node.tag == 'linearGradient':
					# Similar in pattern
					continue
				elif node.tag == inkex.addNS( 'style', 'svg' ) or node.tag == 'style':
					# This is a reference to an external style sheet and not the value
					# of a style attribute to be inherited by child elements
					continue
				elif node.tag == inkex.addNS( 'cursor', 'svg' ) or node.tag == 'cursor':
					continue
				elif node.tag == inkex.addNS( 'color-profile', 'svg' ) or node.tag == 'color-profile':
					# Gamma curves, color temp, etc. are not relevant to single color output
					continue
				elif not isinstance( node.tag, basestring ):
					# This is likely an XML processing instruction such as an XML
					# comment.  lxml uses a function reference for such node tags
					# and as such the node tag is likely not a printable string.
					# Further, converting it to a printable string likely won't
					# be very useful.
					continue
				else:
					if (str( node.tag ) not in self.warnings) and (self.plotCurrentLayer):
						t = str( node.tag ).split( '}' )
						inkex.errormsg( gettext.gettext( 'Warning: in layer "' +
							self.sCurrentLayerName + '" unable to draw <' + str( t[-1] ) +
							'> object, please convert it to a path first.' ) )
						self.warnings[str( node.tag )] = 1
					continue

	def DoWePlotLayer( self, strLayerName ):
		"""
		Parse layer name for layer number and other properties.

		First: scan layer name for first non-numeric character,
		and scan the part before that (if any) into a number
		Then, (if not printing in all-layers mode)
		see if the number matches the layer number that we are printing.

		Secondary function: Parse characters following the layer number (if any) to see if
		there is a "+H" or "+S" escape code, that indicates that overrides the pen-down
		height or speed for the given layer. We also check for the "%" leading character,
		which indicates a layer that should be skipped.
		"""

		# Look at layer name.  Sample first character, then first two, and
		# so on, until the string ends or the string no longer consists of digit characters only.
		TempNumString = 'x'
		stringPos = 1
		layerNameInt = -1
		layerMatch = False
		if sys.version_info < (3,): # Yes this is ugly. More elegant suggestions welcome. :)
			CurrentLayerName = strLayerName.encode( 'ascii', 'ignore' ) #Drop non-ascii characters
		else:
			CurrentLayerName=str(strLayerName)
		CurrentLayerName.lstrip 		# Remove leading whitespace
		self.plotCurrentLayer = True    # Temporarily assume that we are plotting the layer

		MaxLength = len( CurrentLayerName )
		if MaxLength > 0:
			if CurrentLayerName[0] == '%':
				self.plotCurrentLayer = False	#First character is "%" -- skip this layer
			while stringPos <= MaxLength:
				LayerNameFragment = CurrentLayerName[:stringPos]
				if (LayerNameFragment.isdigit()):
					TempNumString = CurrentLayerName[:stringPos] # Store longest numeric string so far
					stringPos = stringPos + 1
				else:
					break

		if (self.PrintInLayersMode):	#Also true if resuming a print that was of a single layer.
			if ( str.isdigit( TempNumString ) ):
				layerNameInt = int( float( TempNumString ) )
				if ( self.svgLayer == layerNameInt ):
					layerMatch = True	#Match! The current layer IS named.

			if (layerMatch == False):
				self.plotCurrentLayer = False

		if (self.plotCurrentLayer == True):
			self.LayersFoundToPlot = True

			#End of part 1, current layer to see if we print it.
			#Now, check to see if there is additional information coded here.

			oldPenDown = self.LayerPenDownPosition
			oldSpeed = self.LayerPenDownSpeed

			#set default values before checking for any overrides:
			self.UseCustomLayerPenHeight = False
			self.UseCustomLayerSpeed = False
			self.LayerPenDownPosition = -1
			self.LayerPenDownSpeed = -1

			if (stringPos > 0):
				stringPos = stringPos - 1

			if MaxLength > stringPos + 2:
				while stringPos <= MaxLength:
					EscapeSequence = CurrentLayerName[stringPos:stringPos+2].lower()
					if (EscapeSequence == "+h") or (EscapeSequence == "+s"):
						paramStart = stringPos + 2
						stringPos = stringPos + 3
						TempNumString = 'x'
						if MaxLength > 0:
							while stringPos <= MaxLength:
								if str.isdigit( CurrentLayerName[paramStart:stringPos] ):
									TempNumString = CurrentLayerName[paramStart:stringPos] # Longest numeric string so far
									stringPos = stringPos + 1
								else:
									break
						if ( str.isdigit( TempNumString ) ):
							parameterInt = int( float( TempNumString ) )

							if (EscapeSequence == "+h"):
								if ((parameterInt >= 0) and (parameterInt <= 100)):
									self.UseCustomLayerPenHeight = True
									self.LayerPenDownPosition = parameterInt

							if (EscapeSequence == "+s"):
								if ((parameterInt > 0) and (parameterInt <= 100)):
									self.UseCustomLayerSpeed = True
									self.LayerPenDownSpeed = parameterInt

						stringPos = paramStart + len(TempNumString)
					else:
						break #exit loop.

			if (self.LayerPenDownSpeed != oldSpeed):
				self.EnableMotors()	#Set speed value variables for this layer.
			if (self.LayerPenDownPosition != oldPenDown):
				self.ServoSetup()	#Set pen height value variables for this layer.

	def plotPath( self, path, matTransform ):
		'''
		Plot the path while applying the transformation defined by the matrix [matTransform].
		- Turn this path into a cubicsuperpath (list of beziers).
		- We also identify "even and odd" parts of the path, to decide when the pen is up and down.
		'''

		d = path.get( 'd' )

		if self.spewDebugdata:
			inkex.errormsg( 'plotPath()\n')
			inkex.errormsg( 'path d: ' + d)
			if len( simplepath.parsePath( d ) ) == 0:
				inkex.errormsg( 'path length is zero, will not be plotting this path.')

		if (len(d) > 3000):			# Raise pen when computing extremely long paths.
			if (self.penUp != True):	# skip if pen is already up
				self.penRaise()

		if len( simplepath.parsePath( d ) ) == 0:
			return

		if self.plotCurrentLayer:
			p = cubicsuperpath.parsePath( d )

			# ...and apply the transformation to each point
			applyTransformToPath( matTransform, p )

			# p is now a list of lists of cubic beziers [control pt1, control pt2, endpoint]
			# where the start-point is the last point in the previous segment.
			for sp in p:

				plot_utils.subdivideCubicPath( sp, 0.02 / self.options.smoothness )
				nIndex = 0

				singlePath = []
				if self.plotCurrentLayer:
					for csp in sp:
						if self.bStopped:
							return
						if (self.printPortrait):
							fX = float( csp[1][1] ) #Flipped X/Y
							fY = ( self.svgWidth) - float( csp[1][0] )
						else:
							fX = float( csp[1][0] ) # Set move destination
							fY = float( csp[1][1] )

						if nIndex == 0:
							if (plot_utils.distance(fX - self.fCurrX,fY - self.fCurrY) > axidraw_conf.MinGap):
								self.penRaise()
								self.plotSegmentWithVelocity( fX, fY, 0, 0)	# Pen up straight move, zero velocity at endpoints
						elif nIndex == 1:
							self.penLower()
						nIndex += 1

						singlePath.append([fX,fY])

					self.PlanTrajectory(singlePath)

			if ( not self.bStopped ):	#an "index" for resuming plots quickly-- record last complete path
				self.svgLastPath = self.pathcount #The number of the last path completed
				self.svgLastPathNC = self.nodeCount #the node count after the last path was completed.

	def PlanTrajectory( self, inputPath ):
		'''
		Plan the trajectory for a full path, accounting for linear acceleration.
		Inputs: Ordered (x,y) pairs to cover.
		Old output: A list of segments to plot, of the form (Xfinal, Yfinal, Vinitial, Vfinal)
		New output: A list of segments to plot, of the form (Xfinal, Yfinal, Vix, Viy, Vfx,Vfy)

		Note: Native motor axes are Motor 1, Motor 2:

		motorSteps1 = ( xMovementSteps + yMovementSteps ) / sqrt(2) # Number of native motor steps required, Axis 1
		motorSteps2 = ( xMovementSteps - yMovementSteps ) / sqrt(2) # Number of native motor steps required, Axis 2


		Important note: This routine uses *inch* units (inches, inches/second, etc.).
		'''

		spewTrajectoryDebugData = self.spewDebugdata	#Suggested values: False or self.spewDebugdata

		if spewTrajectoryDebugData:
			inkex.errormsg( '\nPlanTrajectory()\n')

		if self.bStopped:
			return
		if ( self.fCurrX is None ):
			return

		#check page size limits:
		if (self.ignoreLimits == False):
			tolerance = 2 / self.stepsPerInchXY	#Truncate up to 2 steps at boundaries without throwing an error.
			for xy in inputPath:
				xy[0], xBounded = plot_utils.checkLimitsTol( xy[0], self.xBoundsMin, self.xBoundsMax, tolerance )
				xy[1], yBounded = plot_utils.checkLimitsTol( xy[1], self.yBoundsMin, self.yBoundsMax, tolerance )
				if (xBounded or yBounded):
					self.warnOutOfBounds = True

		#Handle simple segments (lines) that do not require any complex planning:
		if (len(inputPath) < 3):
			if spewTrajectoryDebugData:
				inkex.errormsg( 'Drawing straight line, not a curve.')	# This is the "SHORTPATH ESCAPE"
			self.plotSegmentWithVelocity( xy[0], xy[1], 0, 0)
			return

		#For other trajectories, we need to go deeper.
		TrajLength = len(inputPath)

		if spewTrajectoryDebugData:
			inkex.errormsg( 'Input path to PlanTrajectory: ')
			for xy in inputPath:
				inkex.errormsg( 'x: %1.3f,  y: %1.3f' %(xy[0],xy[1]))
			inkex.errormsg( '\nTrajLength: '+str(TrajLength))

		#Absolute maximum and minimum speeds allowed:

		#Values such as PenUpSpeed are in units of _steps per second_ along native axes
		# However, to simplify our kinematic calculations,
		# we will switch into inches per second.

		# Maximum travel speed
		if ( self.penUp ):
			speedLimit = self.penUpSpeed  / self.stepsPerInchXY	# Units of speedLimit: inches/second
		else:
			speedLimit = self.PenDownSpeed  / self.stepsPerInchXY

		TrajDists = array('f')	 #float, Segment length (distance) when arriving at the junction
		TrajVels = array('f')	 #float, Velocity (_speed_, really) when arriving at the junction


		TrajVectors = []		#Array that will hold normalized unit vectors along each segment

		trimmedPath = []		#Array that will hold usable segments of inputPath

		TrajDists.append(0.0)	#First value, at time t = 0
		TrajVels.append(0.0)	#First value, at time t = 0

		minDist = 1.0 / self.stepsPerInchXY	# do not allow moves of less than 1 step.

		lastIndex = 0
		for i in xrange(1, TrajLength):
			#Construct basic arrays of position and distances, skipping zero-length segments.

			#Distance per segment:
			tmpDistX = inputPath[i][0] - inputPath[lastIndex][0]
			tmpDistY = inputPath[i][1] - inputPath[lastIndex][1]

			tmpDist = plot_utils.distance(tmpDistX, tmpDistY)

			if (tmpDist >= minDist):
				TrajDists.append(tmpDist)

				TrajVectors.append([tmpDistX / tmpDist,tmpDistY / tmpDist])		#Normalized unit vectors for computing cosine factor

				tmpX = inputPath[i][0]
				tmpY = inputPath[i][1]
				trimmedPath.append([tmpX,tmpY])		# Selected, usable portions of inputPath.

				if spewTrajectoryDebugData:
					inkex.errormsg( '\nSegment: inputPath[%1.0f] -> inputPath[%1.0f]' %(lastIndex,i))
					inkex.errormsg( 'Destination: x: %1.3f,  y: %1.3f. Move distance: %1.3f' %(tmpX,tmpY,tmpDist))
				lastIndex = i
			elif spewTrajectoryDebugData:
				inkex.errormsg( '\nSegment: inputPath[%1.0f] -> inputPath[%1.0f] is zero (or near zero); skipping!' %(lastIndex,i))
				inkex.errormsg( '  x: %1.3f,  y: %1.3f, distance: %1.3f' %(inputPath[i][0],inputPath[i][1],tmpDist))

		TrajLength = len(TrajDists)

		#Handle zero-length plot:
		if (TrajLength == 1):
			if spewTrajectoryDebugData:
				inkex.errormsg( '\nSkipped a path element that did not have any well-defined segments.')
			return

		#Handle simple segments (lines) that do not require any complex planning (after removing zero-length elements):
		if (TrajLength < 3):
			if spewTrajectoryDebugData:
				inkex.errormsg( '\nDrawing straight line, not a curve.')
			self.plotSegmentWithVelocity( trimmedPath[0][0], trimmedPath[0][1], 0, 0)
			return

		if spewTrajectoryDebugData:
			inkex.errormsg( '\nAfter removing any zero-length segments, we are left with: ' )
			inkex.errormsg( 'trajDists[0]: %1.3f' %(TrajDists[0]))
			for i in xrange(0, len(trimmedPath)):
 				inkex.errormsg( 'i: %1.0f, x: %1.3f,  y: %1.3f, distance: %1.3f' %(i,trimmedPath[i][0],trimmedPath[i][1],TrajDists[i+1]))
 				inkex.errormsg( '  And... trajDists[i+1]: %1.3f' %(TrajDists[i+1]))


		# time to reach full speed (from zero), at maximum acceleration. Defined in settings:
		if ( self.penUp ):
			if ( self.options.resolution == 1 ):	# High-resolution mode
				tMax = axidraw_conf.AccelTimePUHR	#Allow faster pen-up acceleration
			else:
				tMax = axidraw_conf.AccelTimePU
		else:
			tMax = axidraw_conf.AccelTime

		# acceleration/deceleration rate: (Maximum speed) / (time to reach that speed)
		accelRate = speedLimit / tMax

		#Distance that is required to reach full speed, from zero speed:  (1/2) a t^2
		accelDist = 0.5 * accelRate * tMax  * tMax

		if spewTrajectoryDebugData:
			inkex.errormsg( '\nspeedLimit: %1.3f' % speedLimit )
			inkex.errormsg( 'tMax: %1.3f' % tMax )
			inkex.errormsg( 'accelRate: %1.3f' % accelRate )
			inkex.errormsg( 'accelDist: %1.3f' % accelDist )
			CosinePrintArray = array('f')

		'''
		Now, step through every vertex in the trajectory, and calculate what the speed
		should be when arriving at that vertex.

		In order to do so, we need to understand how the trajectory will evolve in terms
		of position and velocity for a certain amount of time in the future, past that vertex.
		The most extreme cases of this is when we are traveling at
		full speed initially, and must come to a complete stop.
			(This is actually more sudden than if we must reverse course-- that must also
			go through zero velocity at the same rate of deceleration, and a full reversal
			that does not occur at the path end might be able to have a
			nonzero velocity at the endpoint.)

		Thus, we look ahead from each vertex until one of the following occurs:
			(1) We have looked ahead by at least tMax, or
			(2) We reach the end of the path.

		The data that we have to start out with is this:
			- The position and velocity at the previous vertex
			- The position at the current vertex
			- The position at subsequent vertices
			- The velocity at the final vertex (zero)

		To determine the correct velocity at each vertex, we will apply the following rules:

		(A) For the first point, V(i = 0) = 0.

		(B) For the last point point, V = 0 as well.

		(C) If the length of the segment is greater than the distance
		required to reach full speed, then the vertex velocity may be as
		high as the maximum speed.

		Note that we must actually check not the total *speed* but the acceleration
		along the two native motor axes.

		(D) If not; if the length of the segment is less than the total distance
		required to get to full speed, then the velocity at that vertex
		is limited by to the value that can be reached from the initial
		starting velocity, in the distance given.

		(E) The maximum velocity through the junction is also limited by the
		turn itself-- if continuing straight, then we do not need to slow down
		as much as if we were fully reversing course.
		We will model each corner as a short curve that we can accelerate around.

		(F) To calculate the velocity through each turn, we must _look ahead_ to
		the subsequent (i+1) vertex, and determine what velocity
		is appropriate when we arrive at the next point.

		Because future points may be close together-- the subsequent vertex could
		occur just before the path end -- we actually must look ahead past the
		subsequent (i + 1) vertex, all the way up to the limits that we have described
		(e.g., tMax) to understand the subsequent behavior. Once we have that effective
		endpoint, we can work backwards, ensuring that we will be able to get to the
		final speed/position that we require.

		A less complete (but far simpler) procedure is to first complete the trajectory
		description, and then -- only once the trajectory is complete -- go back through,
		but backwards, and ensure that we can actually decelerate to each velocity.

		(G) The minimum velocity through a junction may be set to a constant.
		There is often some (very slow) speed -- perhaps a few percent of the maximum speed
		at which there are little or no resonances. Even when the path must directly reverse
		itself, we can usually travel at a non-zero speed. This, of course, presumes that we
		still have a solution for getting to the endpoint at zero speed.
		'''

		delta = self.options.cornering / 1000  #Corner rounding/tolerance factor-- not sure how high this should be set.

		for i in xrange(1, TrajLength - 1):
			Dcurrent = TrajDists[i]		# Length of the segment leading up to this vertex

# 			DcurrentX = TrajDists[i]		# Length of the segment leading up to this vertex
# 			DcurrentX = TrajDists[i]		# Length of the segment leading up to this vertex


			VPrevExit = TrajVels[i-1]	# Velocity when leaving previous vertex

			'''
			Velocity at vertex: Part I

			Check to see what our plausible maximum speeds are, from
			acceleration only, without concern about cornering, nor deceleration.
			'''

			if (Dcurrent > accelDist):
				#There _is_ enough distance in the segment for us to either
				# accelerate to maximum speed or come to a full stop before this vertex.
				VcurrentMax = speedLimit
				if spewTrajectoryDebugData:
					inkex.errormsg( 'Speed Limit on vel : '+str(i))
			else:
				#There is _not necessarily_ enough distance in the segment for us to either
				# accelerate to maximum speed or come to a full stop before this vertex.
				# Calculate how much we *can* swing the velocity by:

				VcurrentMax = plot_utils.vFinal_Vi_A_Dx(VPrevExit,accelRate, Dcurrent)
				if (VcurrentMax > speedLimit):
					VcurrentMax = speedLimit

				if spewTrajectoryDebugData:
					inkex.errormsg( 'TrajVels I: %1.3f' % VcurrentMax )

			'''
			Velocity at vertex: Part II

			Assuming that we have the same velocity when we enter and
			leave a corner, our acceleration limit provides a velocity
			that depends upon the angle between input and output directions.

			The cornering algorithm models the corner as a slightly smoothed corner,
			to estimate the angular acceleration that we encounter:
			https://onehossshay.wordpress.com/2011/09/24/improving_grbl_cornering_algorithm/

			The dot product of the unit vectors is equal to the cosine of the angle between the
			two unit vectors, giving the deflection between the incoming and outgoing angles.
			Note that this angle is (pi - theta), in the convention of that article, giving us
			a sign inversion. [cos(pi - theta) = - cos(theta)]
			'''

			cosineFactor = plot_utils.dotProductXY(TrajVectors[i - 1],TrajVectors[i])

			if (cosineFactor < 0):
				VjunctionMax = 0
			else:
				VjunctionMax = speedLimit * 0.1 + 0.9 * cosineFactor

			if (VcurrentMax > VjunctionMax):
				VcurrentMax = VjunctionMax

			TrajVels.append( VcurrentMax)	# "Forward-going" speed limit for velocity at this particular vertex.
		TrajVels.append( 0.0 )				# Add zero velocity, for final vertex.

		if spewTrajectoryDebugData:
			inkex.errormsg( ' ')
			for dist in CosinePrintArray:
				inkex.errormsg( 'Cosine Factor: %1.3f' % dist )
			inkex.errormsg( ' ')

			for dist in TrajVels:
				inkex.errormsg( 'TrajVels II: %1.3f' % dist )
			inkex.errormsg( ' ')

		'''
		Velocity at vertex: Part III

		We have, thus far, ensured that we could reach the desired velocities, going forward, but
		have also assumed an effectively infinite deceleration rate.

		We now go through the completed array in reverse, limiting velocities to ensure that we
		can properly decelerate in the given distances.
		'''

		for j in xrange(1, TrajLength):
			i = TrajLength - j	# Range: From (TrajLength - 1) down to 1.

			Vfinal = TrajVels[i]
			Vinitial = TrajVels[i - 1]
			SegLength = TrajDists[i]

			if (Vinitial > Vfinal) and (SegLength > 0):
				VInitMax = plot_utils.vInitial_VF_A_Dx(Vfinal,-accelRate,SegLength)

				if spewTrajectoryDebugData:
					inkex.errormsg( 'VInit Calc: (Vfinal = %1.3f, accelRate = %1.3f, SegLength = %1.3f) '
					% (Vfinal, accelRate, SegLength))

				if (VInitMax < Vinitial):
					Vinitial = VInitMax
				TrajVels[i - 1] = Vinitial

		if spewTrajectoryDebugData:
			for dist in TrajVels:
				inkex.errormsg( 'TrajVels III: %1.3f' % dist )
			inkex.errormsg( ' ')

# 		if spewTrajectoryDebugData:
# 			inkex.errormsg( 'List results for this input path:')
# 			for i in xrange(0, TrajLength-1):
# 				inkex.errormsg( 'i: %1.0f' %(i))
# 				inkex.errormsg( 'x: %1.3f,  y: %1.3f' %(trimmedPath[i][0],trimmedPath[i][1]))
# 				inkex.errormsg( 'distance: %1.3f' %(TrajDists[i+1]))
# 				inkex.errormsg( 'TrajVels[i]: %1.3f' %(TrajVels[i]))
# 				inkex.errormsg( 'TrajVels[i+1]: %1.3f\n' %(TrajVels[i+1]))

		for i in xrange(0, TrajLength - 1):
			self.plotSegmentWithVelocity( trimmedPath[i][0] , trimmedPath[i][1] ,TrajVels[i] , TrajVels[i+1])

	def plotSegmentWithVelocity( self, xDest, yDest, Vi, Vf ):
		'''
		Control the serial port to command the machine to draw
		a straight line segment, with basic acceleration support.

		Inputs: 	Destination (x,y)
					Initial velocity
					Final velocity

		Method: Divide the segment up into smaller segments, each
		of which has constant velocity.
		Send commands out the com port as a set of short line segments
		(dx, dy) with specified durations (in ms) of how long each segment
		takes to draw.the segments take to draw.
		Uses linear ("trapezoid") acceleration and deceleration strategy.

		Inputs are expected be in units of inches (for distance)
			or inches per second (for velocity).

		Previous input: A list of segments to plot, of the form (Xfinal, Yfinal, Vinitial, Vfinal)
		New input: A list of segments to plot, of the form (Xfinal, Yfinal, Vix, Viy, Vfx,Vfy)

		'''

		self.PauseResumeCheck()

		spewSegmentDebugData = False
		spewSegmentDebugData = self.spewDebugdata

		if spewSegmentDebugData:
			if self.resumeMode or self.bStopped:
				spewText = '\nSkipping '
			else:
				spewText = '\nExecuting '
			spewText += 'plotSegmentWithVelocity() function\n'
			if self.penUp:
				spewText += '  Pen-up transit'
			else:
				spewText += '  Pen-down move'
			spewText += ' from (x = %1.3f, y = %1.3f)' % (self.fCurrX, self.fCurrY)
			spewText += ' to (x = %1.3f, y = %1.3f)\n' % (xDest, yDest)
			spewText += '    w/ Vi = %1.2f, Vf = %1.2f ' % (Vi, Vf)
			inkex.errormsg(spewText)
			if self.resumeMode:
				inkex.errormsg(' -> NOTE: ResumeMode is active')
			if self.bStopped:
				inkex.errormsg(' -> NOTE: Stopped by button press.')

		ConstantVelMode = False
		if (self.options.constSpeed and not self.penUp):
			ConstantVelMode = True

		if self.bStopped:
			return
		if ( self.fCurrX is None ):
			return

		if (self.ignoreLimits == False):	#check page size limits:
			tolerance = 1 / self.stepsPerInchXY	#Truncate up to 1 step at boundaries without throwing an error.
			xDest, xBounded = plot_utils.checkLimitsTol( xDest, self.xBoundsMin, self.xBoundsMax, tolerance )
			yDest, yBounded = plot_utils.checkLimitsTol( yDest, self.yBoundsMin, self.yBoundsMax, tolerance )
			if (xBounded or yBounded):
				self.warnOutOfBounds = True


		deltaXinches =  xDest - self.fCurrX
		deltaYinches =  yDest - self.fCurrY

		# Velocity inputs, in motor-step units.  Recall that self.stepsPerInch is in motor-step units

		Vi_StepsPerSec = Vi * self.stepsPerInch		#Translate from "inches per second"
		Vf_StepsPerSec = Vf * self.stepsPerInch		#Translate from "inches per second"

		# self.stepsPerInch = float( axidraw_conf.DPI_16X * self.sq2)

		# Look at distance to move along 45-degree axes, for native motor steps:
		# Recall that stepsPerInch gives  _native motor steps_ per inch of travel along native axes.
		motorSteps1 = int( round( self.stepsPerInch * ( deltaXinches + deltaYinches ) / self.sq2 ) ) # Number of native motor steps required, Axis 1
		motorSteps2 = int( round( self.stepsPerInch * ( deltaXinches - deltaYinches ) / self.sq2 ) ) # Number of native motor steps required, Axis 2

		plotDistanceSteps = plot_utils.distance( motorSteps1, motorSteps2 )
		if (plotDistanceSteps < 1.0): #if total movement is less than one step, skip this movement.
			return


		if spewSegmentDebugData:
			inkex.errormsg( '\ndeltaYinches: ' + str(deltaXinches) )
			inkex.errormsg( 'deltaYinches: ' + str(deltaYinches) )
			inkex.errormsg( 'motorSteps1: ' + str(motorSteps1) )
			inkex.errormsg( 'motorSteps2: ' + str(motorSteps2) )
			inkex.errormsg( 'plotDistanceSteps: ' + str(plotDistanceSteps) )

		if (self.options.reportTime): #Also keep track of distance:
			if self.penUp:
				self.penUpDistSteps = self.penUpDistSteps + plotDistanceSteps
			else:
				self.penDownDistSteps = self.penDownDistSteps + plotDistanceSteps

		# Maximum travel speeds:
		# & acceleration/deceleration rate: (Maximum speed) / (time to reach that speed)

		if ( self.penUp ):
			speedLimit = self.penUpSpeed
			if ( self.options.resolution == 1 ):	# High-resolution mode
				accelRate = speedLimit / axidraw_conf.AccelTimePUHR	#Allow faster pen-up acceleration
			else:
				accelRate = speedLimit / axidraw_conf.AccelTimePU

			if plotDistanceSteps < (self.stepsPerInch * axidraw_conf.ShortThreshold):
				accelRate = speedLimit / axidraw_conf.AccelTime
				speedLimit = self.PenDownSpeed
		else:
			speedLimit = self.PenDownSpeed
			accelRate = speedLimit / axidraw_conf.AccelTime

		if (Vi_StepsPerSec > speedLimit):
			Vi_StepsPerSec = speedLimit
		if (Vf_StepsPerSec > speedLimit):
			Vf_StepsPerSec = speedLimit

		#Times to reach maximum speed, from our initial velocity
		# vMax = vi + a*t  =>  t = (vMax - vi)/a
		# vf = vMax - a*t   =>  t = -(vf - vMax)/a = (vMax - vf)/a
		# -- These are _maximum_ values. We often do not have enough time/space to reach full speed.

		tAccelMax = (speedLimit - Vi_StepsPerSec) / accelRate
		tDecelMax = (speedLimit - Vf_StepsPerSec) / accelRate

		if spewSegmentDebugData:
			inkex.errormsg( '\naccelRate: ' + str(accelRate) )
			inkex.errormsg( 'speedLimit: ' + str(speedLimit) )
			inkex.errormsg( 'Vi_StepsPerSec: ' + str(Vi_StepsPerSec) )
			inkex.errormsg( 'Vf_StepsPerSec: ' + str(Vf_StepsPerSec) )
			inkex.errormsg( 'tAccelMax: ' + str(tAccelMax) )
			inkex.errormsg( 'tDecelMax: ' + str(tDecelMax) )

		#Distance that is required to reach full speed, from our start at speed Vi_StepsPerSec:
		# distance = vi * t + (1/2) a t^2
		accelDistMax = ( Vi_StepsPerSec * tAccelMax ) + ( 0.5 * accelRate * tAccelMax * tAccelMax )
		# Use the same model for deceleration distance; modeling it with backwards motion:
		decelDistMax = ( Vf_StepsPerSec * tDecelMax ) + ( 0.5 * accelRate * tDecelMax * tDecelMax )

		#time slices: Slice travel into intervals that are (say) 30 ms long.
		timeSlice = axidraw_conf.TimeSlice	#Default slice intervals

		# Declare arrays:
		# These are _normally_ 4-byte integers, but could (theoretically) be 2-byte integers on some systems.
		#   if so, this could cause errors in rare cases (very large/long moves, etc.).
		# Set up an alert system, just in case!

		durationArray = array('I') # unsigned integer for duration -- up to 65 seconds for a move if only 2 bytes.
		distArray = array('f')	#float
		destArray1 = array('i')	#signed integer
		destArray2 = array('i')	#signed integer

		timeElapsed = 0.0
		position = 0.0
		velocity = Vi_StepsPerSec

		'''

		Next, we wish to estimate total time duration of this segment.
		In doing so, we must consider the possible cases:

		Case 1: 'Trapezoid'
			Segment length is long enough to reach full speed.
			Segment length > accelDistMax + decelDistMax
			We will get to full speed, with an opportunity to "coast" at full speed
			in the middle.

		Case 2: 'Triangle'
			Segment length is not long enough to reach full speed.
			Accelerate from initial velocity to a local maximum speed,
			then decelerate from that point to the final velocity.

		Case 3: 'Linear velocity ramp'
			For small enough moves -- say less than 10 intervals (typ 500 ms),
			we do not have significant time to ramp the speed up and down.
			Instead, perform only a simple speed ramp between initial and final.

		Case 4: 'Constant velocity'
			Use a single, constant velocity for all pen-down movements.
			Also a fallback position, when moves are too short for linear ramps.

		In each case, we ultimately construct the trajectory in segments at constant velocity.
		In cases 1-3, that set of segments approximates a linear slope in velocity.

		Because we may end up with slight over/undershoot in position along the paths
		with this approach, we perform a final scaling operation (to the correct distance) at the end.

		'''

		if (ConstantVelMode == False) or ( self.penUp ):	#Allow accel when pen is up.
			if (plotDistanceSteps > (accelDistMax + decelDistMax + timeSlice * speedLimit)):
				'''
				Case 1: 'Trapezoid'
				'''

				if spewSegmentDebugData:
					inkex.errormsg( 'Type 1: Trapezoid'+ '\n')
				speedMax = speedLimit	# We will reach _full cruising speed_!

				intervals = int(math.floor(tAccelMax / timeSlice))	# Number of intervals during acceleration

				#If intervals == 0, then we are already at (or nearly at) full speed.
				if (intervals > 0):
					timePerInterval = tAccelMax / intervals

					velocityStepSize = (speedMax - Vi_StepsPerSec)/(intervals + 1.0)
					# For six time intervals of acceleration, first interval is at velocity (max/7)
					# 6th (last) time interval is at 6*max/7
					# after this interval, we are at full speed.

					for index in xrange(0, intervals):		#Calculate acceleration phase
						velocity += velocityStepSize
						timeElapsed += timePerInterval
						position += velocity * timePerInterval
						durationArray.append(int(round(timeElapsed * 1000.0)))
						distArray.append(position)		#Estimated distance along direction of travel
					if spewSegmentDebugData:
						inkex.errormsg( 'Accel intervals: '+str(intervals))

				#Add a center "coasting" speed interval IF there is time for it.
				coastingDistance = plotDistanceSteps - (accelDistMax + decelDistMax)

				if (coastingDistance > (timeSlice * speedMax)):
					# There is enough time for (at least) one interval at full cruising speed.
					velocity = speedMax
					cruisingTime = coastingDistance / velocity
					timeElapsed += cruisingTime
					durationArray.append(int(round(timeElapsed * 1000.0)))
					position += velocity * cruisingTime
					distArray.append(position)		#Estimated distance along direction of travel
					if spewSegmentDebugData:
						inkex.errormsg( 'Coast Distance: '+str(coastingDistance))

				intervals = int(math.floor(tDecelMax / timeSlice))	# Number of intervals during deceleration

				if (intervals > 0):
					timePerInterval = tDecelMax / intervals
					velocityStepSize = (speedMax - Vf_StepsPerSec)/(intervals + 1.0)

					for index in xrange(0, intervals):		#Calculate deceleration phase
						velocity -= velocityStepSize
						timeElapsed += timePerInterval
						position += velocity * timePerInterval
						durationArray.append(int(round(timeElapsed * 1000.0)))
						distArray.append(position)		#Estimated distance along direction of travel
					if spewSegmentDebugData:
						inkex.errormsg( 'Decel intervals: '+str(intervals))

			else:
				'''
				Case 2: 'Triangle'

				We will _not_ reach full cruising speed, but let's go as fast as we can!

				We begin with given: initial velocity, final velocity,
					maximum acceleration rate, distance to travel.

				The optimal solution is to accelerate at the maximum rate, to some maximum velocity Vmax,
				and then to decelerate at same maximum rate, to the final velocity.
				This forms a triangle on the plot of V(t).

				The value of Vmax -- and the time at which we reach it -- may be varied in order to
				accommodate our choice of distance-traveled and velocity requirements.
				(This does assume that the segment requested is self consistent, and planned
				with respect to our acceleration requirements.)

				In a more detail, with short notation Vi = Vi_StepsPerSec, Vf = Vf_StepsPerSec,
					Amax = accelRate, Dv = (Vf - Vi)

				(i) We accelerate from Vi, at Amax to some maximum velocity Vmax.
				This takes place during an interval of time Ta.

				(ii) We then decelerate from Vmax, to Vf, at the same maximum rate, Amax.
				This takes place during an interval of time Td.

				(iii) The total time elapsed is Ta + Td

				(iv) v = v0 + a * t
					=>	Vmax = Vi + Amax * Ta
					and	Vmax = Vf + Amax * Td    (i.e., Vmax - Amax * Td = Vf)

					Thus Td = Ta - (Vf - Vi) / Amax, or    Td = Ta - (Dv / Amax)

				(v) The distance covered during the acceleration interval Ta is given by:
					Xa = Vi * Ta + (1/2) Amax * Ta^2

					The distance covered during the deceleration interval Td is given by:
					Xd = Vf * Td + (1/2) Amax * Td^2

					Thus, the total distance covered during interval Ta + Td is given by:
					plotDistanceSteps = Xa + Xd = Vi * Ta + (1/2) Amax * Ta^2 + Vf * Td + (1/2) Amax * Td^2

				(vi) Now substituting in Td = Ta - (Dv / Amax), we find:
					Amax * Ta^2 + 2 * Vi * Ta + ( Vi^2 - Vf^2 )/( 2 * Amax ) - plotDistanceSteps = 0

					Solving this quadratic equation for Ta, we find:
					Ta = ( sqrt(2 * Vi^2 + 2 * Vf^2 + 4 * Amax * plotDistanceSteps) - 2 * Vi ) / ( 2 * Amax )

					[We pick the positive root in the quadratic formula, since Ta must be positive.]

				(vii) From Ta and part (iv) above, we can find Vmax and Td.
				'''

				if spewSegmentDebugData:
					inkex.errormsg( '\nType 2: Triangle' )

				if (plotDistanceSteps >=  0.9 * (accelDistMax + decelDistMax)):
					accelRateLocal = 0.9 * ((accelDistMax + decelDistMax) / plotDistanceSteps) * accelRate
					if spewSegmentDebugData:
						inkex.errormsg( 'accelRateLocal changed')
				else:
# 					inkex.errormsg( 'Vmax unchanged: ')
					accelRateLocal = accelRate

				Ta = ( math.sqrt(2 * Vi_StepsPerSec * Vi_StepsPerSec + 2 * Vf_StepsPerSec * Vf_StepsPerSec + 4 * accelRateLocal * plotDistanceSteps)
					- 2 * Vi_StepsPerSec ) / ( 2 * accelRateLocal )

				if (Ta < 0) :
					Ta = 0
					if spewSegmentDebugData:
						inkex.errormsg( 'Warning: Negative transit time computed.') # Should not happen. :)

				Vmax = Vi_StepsPerSec + accelRateLocal * Ta
				if spewSegmentDebugData:
					inkex.errormsg( 'Vmax: '+str(Vmax))



				intervals = int(math.floor(Ta / timeSlice))	# Number of intervals during acceleration

				if (intervals == 0):
					Ta = 0
				Td = Ta - (Vf_StepsPerSec - Vi_StepsPerSec) / accelRateLocal
				Dintervals = int(math.floor(Td / timeSlice))	# Number of intervals during acceleration

				if ((intervals + Dintervals) > 4):
					if (intervals > 0):
						if spewSegmentDebugData:
							inkex.errormsg( 'Triangle intervals UP: '+str(intervals))

						timePerInterval = Ta / intervals
						velocityStepSize = (Vmax - Vi_StepsPerSec)/(intervals + 1.0)
						# For six time intervals of acceleration, first interval is at velocity (max/7)
						# 6th (last) time interval is at 6*max/7
						# after this interval, we are at full speed.

						for index in xrange(0, intervals):		#Calculate acceleration phase
							velocity += velocityStepSize
							timeElapsed += timePerInterval
							position += velocity * timePerInterval
							durationArray.append(int(round(timeElapsed * 1000.0)))
							distArray.append(position)		#Estimated distance along direction of travel
					else:
						if spewSegmentDebugData:
							inkex.errormsg( 'Note: Skipping accel phase in triangle.')

					if (Dintervals > 0):
						if spewSegmentDebugData:
							inkex.errormsg( 'Triangle intervals Down: '+str(Dintervals))

						timePerInterval = Td / Dintervals
						velocityStepSize = (Vmax - Vf_StepsPerSec)/(Dintervals + 1.0)
						# For six time intervals of acceleration, first interval is at velocity (max/7)
						# 6th (last) time interval is at 6*max/7
						# after this interval, we are at full speed.

						for index in xrange(0, Dintervals):		#Calculate acceleration phase
							velocity -= velocityStepSize
							timeElapsed += timePerInterval
							position += velocity * timePerInterval
							durationArray.append(int(round(timeElapsed * 1000.0)))
							distArray.append(position)		#Estimated distance along direction of travel
					else:
						if spewSegmentDebugData:
							inkex.errormsg( 'Note: Skipping decel phase in triangle.')
				else:
					'''
					Case 3: 'Linear or constant velocity changes'

					Picked for segments that are shorter than 6 time slices.
					Linear velocity interpolation between two endpoints.

					Because these are typically short segments (not enough time for a good "triangle"--
					we slightly boost the starting speed, by taking its average with Vmax for the segment.

					For very short segments (less than 2 time slices), use a single
						segment with constant velocity.
					'''

					if spewSegmentDebugData:
						inkex.errormsg( 'Type 3: Linear'+ '\n')
					# xFinal = vi * t  + (1/2) a * t^2, and vFinal = vi + a * t
					# Combining these (with same t) gives: 2 a x = (vf^2 - vi^2)  => a = (vf^2 - vi^2)/2x
					# So long as this 'a' is less than accelRate, we can linearly interpolate in velocity.

					Vi_StepsPerSec = ( Vmax + Vi_StepsPerSec) / 2  	#Boost initial speed for this segment
					velocity = Vi_StepsPerSec					#Boost initial speed for this segment

					localAccel = (Vf_StepsPerSec * Vf_StepsPerSec - Vi_StepsPerSec * Vi_StepsPerSec)/ (2.0 * plotDistanceSteps)

					if (localAccel > accelRate):
						localAccel = accelRate
					elif (localAccel < -accelRate):
						localAccel = -accelRate
					if (localAccel == 0):
						#Initial velocity = final velocity -> Skip to constant velocity routine.
						ConstantVelMode = True
					else:
						tSegment = (Vf_StepsPerSec - Vi_StepsPerSec) / localAccel

					intervals = int(math.floor(tSegment / timeSlice))	# Number of intervals during deceleration
					if (intervals > 1):
						timePerInterval = tSegment / intervals
						velocityStepSize = (Vf_StepsPerSec - Vi_StepsPerSec)/(intervals + 1.0)
						# For six time intervals of acceleration, first interval is at velocity (max/7)
						# 6th (last) time interval is at 6*max/7
						# after this interval, we are at full speed.

						for index in xrange(0, intervals):		#Calculate acceleration phase
							velocity += velocityStepSize
							timeElapsed += timePerInterval
							position += velocity * timePerInterval
							durationArray.append(int(round(timeElapsed * 1000.0)))
							distArray.append(position)		#Estimated distance along direction of travel
					else:
						#Short segment; Not enough time for multiple segments at different velocities.
						Vi_StepsPerSec = Vmax #These are _slow_ segments-- use fastest possible interpretation.
						ConstantVelMode = True

		if (ConstantVelMode):
			'''
			Case 4: 'Constant Velocity mode'
			'''
			if spewSegmentDebugData:
				inkex.errormsg( '-> [Constant Velocity Mode Segment]'+ '\n')
			#Single segment with constant velocity.

			if (self.options.constSpeed and not self.penUp):
				velocity = self.PenDownSpeed 	#Constant pen-down speed
			elif (Vf_StepsPerSec > Vi_StepsPerSec):
				velocity = Vf_StepsPerSec
			elif (Vi_StepsPerSec > Vf_StepsPerSec):
				velocity = Vi_StepsPerSec
			elif (Vi_StepsPerSec > 0):	#Allow case of two are equal, but nonzero
				velocity = Vi_StepsPerSec
			else: #Both endpoints are equal to zero.
				velocity = self.PenDownSpeed /10

			if spewSegmentDebugData:
				inkex.errormsg( 'velocity: '+str(velocity))

			timeElapsed = plotDistanceSteps / velocity
			durationArray.append(int(round(timeElapsed * 1000.0)))
			distArray.append(plotDistanceSteps)		#Estimated distance along direction of travel
			position += plotDistanceSteps

		'''
		The time & distance motion arrays for this path segment are now computed.
		Next: We scale to the correct intended travel distance,
		round into integer motor steps and manage the process
		of sending the output commands to the motors.
		'''

		if spewSegmentDebugData:
			inkex.errormsg( 'position/plotDistanceSteps: '+str(position/plotDistanceSteps))

		for index in xrange (0, len(distArray) ):
			#Scale our trajectory to the "actual" travel distance that we need:
			fractionalDistance = distArray[index] / position # Fractional position along the intended path
			destArray1.append (int(round( fractionalDistance * motorSteps1)))
			destArray2.append (int(round( fractionalDistance * motorSteps2)))

		prevMotor1 = 0
		prevMotor2 = 0
		prevTime = 0

		for index in xrange (0, len(destArray1) ):
			moveSteps1 = destArray1[index] - prevMotor1
			moveSteps2 = destArray2[index] - prevMotor2
			moveTime = durationArray[index] - prevTime
			prevTime = durationArray[index]

			if ( moveTime < 1 ):
				moveTime = 1	# don't allow zero-time moves.

			if (abs((float(moveSteps1) / float(moveTime))) < 0.002):
				moveSteps1 = 0	#don't allow too-slow movements of this axis
			if (abs((float(moveSteps2) / float(moveTime))) < 0.002):
				moveSteps2 = 0	#don't allow too-slow movements of this axis

			prevMotor1 += moveSteps1
			prevMotor2 += moveSteps2

			xSteps = (moveSteps1 + moveSteps2) / self.sq2	# Result will be a float.
			ySteps = (moveSteps1 - moveSteps2) / self.sq2

			if ((moveSteps1 != 0) or (moveSteps2 != 0)): # if at least one motor step is required for this move.
				if (not self.resumeMode) and (not self.bStopped):

					fNewX = self.fCurrX + (xSteps / self.stepsPerInch)
					fNewY = self.fCurrY + (ySteps / self.stepsPerInch)

					if self.options.previewOnly:
						self.ptEstimate += moveTime
						if (self.options.previewType > 0):		# Generate preview paths

							if (self.velDataPlot):
								velocityLocal1 = moveSteps1 / float(moveTime)
								velocityLocal2 = moveSteps2 / float(moveTime)
								velocityLocal =  plot_utils.distance( moveSteps1, moveSteps2 ) / float(moveTime)
								self.updateVCharts( velocityLocal1, velocityLocal2, velocityLocal)
								self.velDataTime += moveTime
								self.updateVCharts( velocityLocal1, velocityLocal2, velocityLocal)
							if (self.printPortrait):
								xNewt = self.DocUnitScaleFactor * (self.svgWidth - fNewY)
								yNewt = self.DocUnitScaleFactor * fNewX
								xOldt = self.DocUnitScaleFactor * (self.svgWidth - self.fCurrY)
								yOldt = self.DocUnitScaleFactor * self.fCurrX
							else:
								xNewt = self.DocUnitScaleFactor * fNewX
								yNewt = self.DocUnitScaleFactor * fNewY
								xOldt = self.DocUnitScaleFactor * self.fCurrX
								yOldt = self.DocUnitScaleFactor * self.fCurrY
							if self.penUp:
								if (self.options.previewType > 1): # previewType is 2 or 3. Show pen-up movement
									if (self.pathDataPenUp != 1):
										self.pathDataPU.append("M%0.3f %0.3f" % (xOldt, yOldt) )
										self.pathDataPenUp = 1	# Reset pen state indicator
									self.pathDataPU.append(" %0.3f %0.3f" % ( xNewt, yNewt) )
							else:
								if ((self.options.previewType == 1) or (self.options.previewType == 3)): #If 1 or 3, show pen-down movement
									if (self.pathDataPenUp != 0):
										self.pathDataPD.append("M%0.3f %0.3f" % ( xOldt, yOldt) )
										self.pathDataPenUp = 0 # Reset pen state indicator
									self.pathDataPD.append(" %0.3f %0.3f" % ( xNewt,  yNewt) )
					else:
						ebb_motion.doXYMove( self.serialPort, moveSteps2, moveSteps1, moveTime )
						if (moveTime > 50):
							if self.options.mode != "manual":
								time.sleep(float(moveTime - 10)/1000.0)  #pause before issuing next command

# 					if ((moveSteps1 / moveTime) >= 25.0):
# 						inkex.errormsg( 'Motor 1 error: ({}, {}), in {} ms'.format(moveSteps1,moveSteps2,moveTime))
# 					if ((moveSteps2 / moveTime) >= 25.0):
# 						inkex.errormsg( 'Motor 2 error: ({}, {}), in {} ms'.format(moveSteps1,moveSteps2,moveTime))

					if spewSegmentDebugData:
						inkex.errormsg( 'XY move:({}, {}), in {} ms'.format(moveSteps1,moveSteps2,moveTime))
						inkex.errormsg( 'fNew(X,Y) :({:.2}, {:.2})'.format(fNewX,fNewY))

					self.fCurrX = fNewX   # Update current position
					self.fCurrY = fNewY

					self.svgLastKnownPosX = self.fCurrX - axidraw_conf.StartPosX
					self.svgLastKnownPosY = self.fCurrY - axidraw_conf.StartPosY
					#if spewSegmentDebugData:
					#	inkex.errormsg( '\nfCurrX,fCurrY (x = %1.2f, y = %1.2f) ' % (self.fCurrX, self.fCurrY))

	def PauseResumeCheck (self):
		# Pause & Resume functionality is managed here, called (for example) while planning
		# a segment to plot. First check to see if the pause button has been pressed.
		# Increment the node counter.
		# Resume drawing if we were in resume mode and supposed to resume at this node.

		if self.bStopped:
			return	# We have _already_ halted the plot due to a button press. No need to proceed.

		if self.options.previewOnly:
			strButton = ['0']
		else:
			strButton = ebb_motion.QueryPRGButton(self.serialPort)	#Query if button pressed

		if (self.debugPause > 0):
			if ((self.nodeCount == self.debugPause) and (self.options.mode == "plot")):
				strButton = ['1']	# simulate pause button press at given node

		if strButton[0] == '1': #button pressed
			self.svgNodeCount = self.nodeCount
			self.svgPausedPosX = self.fCurrX - axidraw_conf.StartPosX
			self.svgPausedPosY = self.fCurrY - axidraw_conf.StartPosY
			self.penRaise()
			inkex.errormsg( 'Plot paused by button press after node number ' + str( self.nodeCount ) + '.' )
			inkex.errormsg( 'Use the "resume" feature to continue.' )
			self.bStopped = True
			return # Note: This segment is not plotted.

		self.nodeCount += 1		# This whole segment move counts as ONE pause/resume node in our plot

		if self.resumeMode:
			if ( self.nodeCount >= (self.nodeTarget)):
				self.resumeMode = False
				if self.spewDebugdata:
					inkex.errormsg( '\nRESUMING PLOT at node : ' + str(self.nodeCount) )
					inkex.errormsg( '\nself.virtualPenUp : ' + str(self.virtualPenUp) )
					inkex.errormsg( '\nself.penUp : ' + str(self.penUp) )
				if ( not self.virtualPenUp ):	# This is the point where we switch from virtual to real pen
					self.penLower()

	def EnableMotors( self ):
		'''
		Enable motors, set native motor resolution, and set speed scales.

		The "pen down" speed scale is adjusted with the following factors
		that make the controls more intuitive:
		* Reduce speed by factor of 2 when using 8X microstepping
		* Reduce speed by factor of 2 when disabling acceleration

		These factors prevent unexpected dramatic changes in speed when turning
		those two options on and off.
		'''

		if (self.UseCustomLayerSpeed):
			LocalPenDownSpeed = self.LayerPenDownSpeed
		else:
			LocalPenDownSpeed = self.options.penDownSpeed

		if ( self.options.resolution == 1 ):
			if not (self.options.previewOnly):
				ebb_motion.sendEnableMotors(self.serialPort, 1) # 16X microstepping
			self.stepsPerInch = float( axidraw_conf.DPI_16X * self.sq2)	# Resolution along native motor axes (not XY)
			self.stepsPerInchXY = float( axidraw_conf.DPI_16X) # Resolution along XY Axes
			self.PenDownSpeed = LocalPenDownSpeed * axidraw_conf.SpeedScale / 110.0		#steps/second along native axis
			self.penUpSpeed = self.options.penUpSpeed * axidraw_conf.SpeedScale / 110.0 #steps/second along native axis
		elif ( self.options.resolution == 2 ):
			if not (self.options.previewOnly):
				ebb_motion.sendEnableMotors(self.serialPort, 2) # 8X microstepping
			self.stepsPerInch = float( axidraw_conf.DPI_16X * self.sq2 / 2.0 )	# Resolution along native motor axes (not XY)
			self.stepsPerInchXY = float( axidraw_conf.DPI_16X / 2.0 )	# Resolution along XY (not native) axes
			self.PenDownSpeed = LocalPenDownSpeed * axidraw_conf.SpeedScale / 220.0		#steps/second along native axis
			self.penUpSpeed = self.options.penUpSpeed * axidraw_conf.SpeedScale / 110.0	#steps/second along native axis
		if (self.options.constSpeed):
			self.PenDownSpeed = self.PenDownSpeed / 3

	def penRaise( self ):
		self.virtualPenUp = True  # Virtual pen keeps track of state for resuming plotting.
		if ( not self.resumeMode) and (self.penUp != True):	# skip if pen is already up, or if we're resuming.
			if (self.UseCustomLayerPenHeight):
				penDownPos = self.LayerPenDownPosition
			else:
				penDownPos = self.options.penDownPosition
			vDistance = float(self.options.penUpPosition - penDownPos)
			vTime = int ((1000.0 * vDistance) / self.options.penLiftRate)
			if (vTime < 0):	#Handle case that penDownPosition is above penUpPosition
				vTime = -vTime
			vTime += self.options.penLiftDelay
			if (vTime < 0): #Do not allow negative delay times
				vTime = 0
			if self.options.previewOnly:
				self.updateVCharts( 0, 0, 0)
				self.velDataTime += vTime
				self.updateVCharts( 0, 0, 0)
			else:
				ebb_motion.sendPenUp(self.serialPort, vTime )
				if (vTime > 50):
					if self.options.mode != "manual":
						time.sleep(float(vTime - 10)/1000.0)  #pause before issuing next command
			self.penUp = True
		self.pathDataPenUp = -1

	def penLower( self ):
		self.virtualPenUp = False  # Virtual pen keeps track of state for resuming plotting.
		if (self.penUp != False):  # skip if pen is already down
			if ((not self.resumeMode) and ( not self.bStopped )): #skip if resuming or stopped
				if (self.UseCustomLayerPenHeight):
					penDownPos = self.LayerPenDownPosition
				else:
					penDownPos = self.options.penDownPosition
				vDistance = float(self.options.penUpPosition - penDownPos)
				vTime = int ((1000.0 * vDistance) / self.options.penLowerRate)
				if (vTime < 0):	#Handle case that penDownPosition is above penUpPosition
					vTime = -vTime
				vTime += self.options.penLowerDelay
				if (vTime < 0): #Do not allow negative delay times
					vTime = 0
				if self.options.previewOnly:
					self.updateVCharts( 0, 0, 0)
					self.velDataTime += vTime
					self.updateVCharts( 0, 0, 0)
				else:
					ebb_motion.sendPenDown(self.serialPort, vTime )
					if (vTime > 50):
						if self.options.mode != "manual":
							time.sleep(float(vTime - 10)/1000.0)  #pause before issuing next command
				self.penUp = False
		self.pathDataPenUp = -1

	def ServoSetupWrapper( self ):
		# Assert what the defined "up" and "down" positions of the servo motor should be,
		#    and determine what the pen state is.
		self.ServoSetup()
		if self.options.previewOnly:
			self.penUp = True			#A fine assumption when in preview mode
			self.virtualPenUp = True
		else:
			if ebb_motion.QueryPenUp( self.serialPort ):
				self.penUp = True
				self.virtualPenUp = True
			else:
				self.penUp = False
				self.virtualPenUp = False

	def ServoSetup( self ):
		''' Pen position units range from 0% to 100%, which correspond to
		    a typical timing range of 7500 - 25000 in units of 1/(12 MHz).
		    1% corresponds to ~14.6 us, or 175 units of 1/(12 MHz).
		'''

		if (self.UseCustomLayerPenHeight):
			penDownPos = self.LayerPenDownPosition
		else:
			penDownPos = self.options.penDownPosition

		if not (self.options.previewOnly):
			servo_range = axidraw_conf.ServoMax - axidraw_conf.ServoMin
			servo_slope = float(servo_range) / 100.0

			intTemp = int(round(axidraw_conf.ServoMin + servo_slope * self.options.penUpPosition))
			ebb_motion.setPenUpPos(self.serialPort, intTemp)

			intTemp = int(round(axidraw_conf.ServoMin + servo_slope * penDownPos))
			ebb_motion.setPenDownPos(self.serialPort, intTemp)

			''' Servo speed units are in units of %/second, referring to the
				percentages above.  The EBB takes speeds in units of 1/(12 MHz) steps
				per 24 ms.  Scaling as above, 1% of range in 1 second
				with SERVO_MAX = 28000  and  SERVO_MIN = 7500
				corresponds to 205 steps change in 1 s
				That gives 0.205 steps/ms, or 4.92 steps / 24 ms
				Rounding this to 5 steps/24 ms is sufficient.		'''

			intTemp = 5 * self.options.penLiftRate
			ebb_motion.setPenUpRate(self.serialPort, intTemp)

			intTemp = 5 * self.options.penLowerRate
			ebb_motion.setPenDownRate(self.serialPort, intTemp)

	def getDocProps( self ):
		'''
		Get the document's height and width attributes from the <svg> tag.
		Use a default value in case the property is not present or is
		expressed in units of percentages.
		'''
		self.svgHeight = plot_utils.getLengthInches( self, 'height' )
		self.svgWidth = plot_utils.getLengthInches( self, 'width' )
		if (self.options.autoRotate) and (self.svgHeight > self.svgWidth ):
			self.printPortrait = True
		if ( self.svgHeight == None ) or ( self.svgWidth == None ):
			return False
		else:
			return True

e = AxiDrawClass()
e.affect()


print