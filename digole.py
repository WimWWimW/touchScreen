# -*- coding: utf-8 -*-
import sys
import io
import gc



if (sys.implementation.name == "cpython"):
    # testing environment on pc: 
    import time
    
    const = lambda x: x
    sleep_ms        = lambda ms: time.sleep(ms/1000)
    getTicks_ms     = lambda: 1000 * time.time() 
    def getDeltaTime(t2, t1 = -1):
        if (t1 < 0): t1, t2 = t2, getTicks_ms()
        return t2 - t1
 

else:    
    # deployment environment on micro-controller:
    import utime as time  # @UnresolvedImport
    from micropython import const  # @UnresolvedImport

    sleep_ms        = lambda ms: time.sleep_ms(ms)
    getTicks_ms     = time.ticks_ms
    def getDeltaTime(t2, t1 = -1):
        if (t1 < 0): t1, t2 = t2, getTicks_ms()
        return time.ticks_diff(t2, t1)


   

   

class DigolePrimitive(object):
    
    _maxRecordingSize = 1024
    
    def __init__(self, i2cConnection, address):
        # i2cConnection: open i2c object
        # address: i2c address of the display
        self.i2c        = i2cConnection
        self.address    = address
        self.dataDelay  = 5 # ms (i.e. 40 ms according to documentation)
        self._paperTrail= None
        self.debug      = False
        

    def _write(self, v):
        # All output to the display passes here. For more reliable performance it is cut into 
        # 64-byte pieces, send with a short wait state in between.
        # v: bytes sequence
        if (len(v) > 64):
            for i in range(0, len(v), 64):
                chunk = v[i:i+64]
                self._write(chunk)
                sleep_ms(self.dataDelay)
        else:
            self.i2c.writeto(self.address, v)
            if self.isRecording():
                self._paperTrail.write(v)
            if self.debug:
                print(v)
                

    def _readInt(self):
        # read a two bytes integer from the output buffer. If not available, an ETIMEDOUT may be raised.
        raw = self.i2c.readfrom(self.address, 2)
        # add a tiny delay as oil for proper reading the next value:
        time.sleep_ms(1) 
        return [int.from_bytes(raw, "big")]

    
    def isRecording(self):
        # true if output is currenty being copied
        return self._paperTrail is not None

    
    def startRecording(self):
        # Start recording output to the display in order to collect these data into a binary script 
        # See also: stopRecording()
        if not self.isRecording():
            self._paperTrail = io.BytesIO(b'')
            
            
    def getRecordingSize(self):
        # Return the size of the current recording buffer. If output is not being recorded, 
        # 0 is returned. 
        return 0 if not self.isRecording() else self._paperTrail.seek(0, 2)
    
    
    def stopRecording(self, streamHandler = None, *args):
        # Stop recording output and get the resulting record. If no streamHandler is provided,
        # the recording buffer is returned. This costs extra memory for temporary variables
        # to store the buffer while the stream is being closed.
        # Alternatively, when a streamHandler (function(<stream>)) is defined, a callback is made
        # before the stream is closed. The size of the buffer is returned.
        if not self.isRecording():
            return None
        
        try:
            if streamHandler is not None:
                result = self.getRecordingSize()
                self._paperTrail.seek(0, 0)               
                streamHandler(self._paperTrail, *args)
            else:
                result = self._paperTrail.getvalue()
        finally:
            self._paperTrail.close()
            self._paperTrail = None
            gc.collect()
            
        return result
            
        
    def executeScript(self, binaryInstructions):
        # Send raw binary instractions to the display. See startRecording(), stopRecording(). 
        self._write(binaryInstructions)
        
    
    def _sendCommand(self, command, *args):
        # Send a comand sequence to the display.
        # Arguments of type bytes are passed to _write unchanged; of type string get a trailing zero added,
        # of type int are converted to the propietary 9-bit int format if greater than 255. All other types
        # (except None, which is ignored) are converted to string. 
        for arg in args:
            if type(arg) is bytes:
                # pass unchanged:
                command += arg
            elif type(arg) is int:
                # add extension to 511:
                if arg >= 255:
                    command += b'\xff'
                    arg     -= 255
                command += arg.to_bytes(1, "big")
            elif arg is None:
                pass
            else:
                # treat as string and add trailing zero:
                if not (type(arg) is str):
                    arg = str(arg)
                # add chr(0):
                command += arg.encode("utf-8") + int(0).to_bytes(1, "big")
        self._write(command)
        
            
    def _getFileSize(self, fileName):
        # return size in bytes of a file on disk:
        with open(fileName, "rb") as f:
            f.seek(0, 2) # os.SEEK_END
            return f.tell()
        
        
    def _sendFile(self, fileName):
        # send conent of file on disk as raw data:
        with open(fileName, "rb") as f:
            while True:
                print(end='.')
                chunk = f.read(128)
                if not chunk:
                    print()
                    break
                self._write(chunk)


    def _sendLargeFileSlowly(self, fileName):
        # Slowly send data for those commands tha write to the flash memory and are sensitive
        # to transmission pace.
        size            = self._getFileSize(fileName)
        stdDelay        = self.dataDelay
        self.dataDelay  = 40
        
        # first send size of data to follow:
        self._write(bytes([size//256, size % 256]))
        sleep_ms(200) # wait until device is ready
        
        # then send the data:
        self._sendFile(fileName)
        self._write(b'\ff')# indicater of end of it
        sleep_ms(40)
        
        # reset delay time:
        self.dataDelay  = stdDelay
            

                    
class DigoleBasic(DigolePrimitive):    

    # --------------------------------------------------------------------------------
    #   Text functions
    # --------------------------------------------------------------------------------

    def printText(self, v):
        # Display a string. This command displays v at the current position. 
        # The position is subsequently adjusted automatically; if it reaches
        # the right edge of the screen, it is moved to the beginning of next line.
        # The module calculates the next character line according to the currently used
        # font's size.
        # The values 10 and 13 (\n and \r) move the current position to the next line
        # and the the beginning of current line respectively.
        #
        self._sendCommand(b'TT', v)


    def printTextAt(self, x, y, v, align = 0):
        # Print text relative to (x, y), aligned according to the value of align.
        # This method replaces the rather unfathomable TextAlignment (ALIGNd) function of the
        # display. 
        # x: the horizontal left, centre or right position of the text 
        # y: represents the baseline of the text, not the top.
        # align: 0 (left), 1 (centre) or 2 (right aligned)
        self.setGraphicPosition(x, y)
        self._sendCommand(b'ALIGN', align)
        self.printText(v)


    def newLine(self):
        # Mobes the text position to the start of the next line, respecting font size.
        self._sendCommand(b'TRT')


    def setTextPosition(self, c, r):
        # Set the current text cursor . 
        # The values of c and r represent the column and row value that MCU calculates based on the font's size
        # (usually the width of a space (#32)). The top-left position is (0, 0).
        self._sendCommand(b'TP', c, r)


    def returnToLastTextPos(self):
        # Return the text cursor to the last set position. 
        # After each character is printed on screen, the current position is
        # adjusted. The MCU rememberes the previous position, so if
        # you want print multiple characters at same position, you can use this function. 
        self._sendCommand(b'ETB')


    def offsetTextPosition(self, x, y):
        # Move the text cursor relatively by (x, y).  
        # The range of x,y value is -127~127, it adjusts the current position with the relative value. 
        # eg.: if current position is (46, 30), after calling offsetTextPosition(-10, 5) the new position
        # is: (36, 35).
        self._sendCommand(b'ETO', x, y)



    # --------------------------------------------------------------------------------
    #   Font management
    # --------------------------------------------------------------------------------

    def setFont(self, b):
        # set the active font (0-6 or 200-203). 
        # WARNING: font 6 has numbers only
        if b < 7:
            b = [0,6,10,18,51,120,123][b]
        self._sendCommand(b'SF', b)


    def uploadUserFont(self, index, fileName):
        # Upload a user font.
        # The font us stored into flash memory (conserved during power-off). Note that when the 
        # required memory space is insufficient, the display may crash or store a corrupted font.
        # Fonts can be found at https://codeload.github.com/olikraus/u8glib/zip/master (byte code in c sources).
        # Not all of these fonts are accepted so try them after uploading to the display.
        self._getFileSize(fileName) # file eror, then crash before sending the next command
        self._sendCommand(b'SUF', index)
        self._sendLargeFileSlowly(fileName)


    def useUserFontInFlashChip(self, address):
        # Use user font in flash chip.
        # Command: SFF, follow by 3 bytes of address which the font data in flash chip start from.
        # (not supported by my display, so not tested)
        self._sendCommand(b'SFF', address)
        
        
    # --------------------------------------------------------------------------------
    #   Graphics
    # --------------------------------------------------------------------------------

    def clearScreen(self):
        # Clear screen.
        # Erases the screen panel and fills the screen with the current background color.
        # This function also resets the current font to 0, screen rotation to 0, x
        # position to 0, draw mode to 'C', draw window to full screen, an the line pattern to
        # 0xff.
        self._sendCommand(b'CL')


    def setGraphicPosition(self, x, y):
        # Set the current cursor with pixel precision. Like setTextPosition, but now (x, y) represents a 
        # pixel postion rather than a character location. The top-left position is (0, 0).
        self._sendCommand(b'GP', x, y)


    def drawPixel(self, x, y):
        # Draws a pixel.
        # This function draw a pixel at the (x,y) position using foreground color (set by commands "SC" or "ESC"), 
        # taking into effect the current draw-mode. This function doesn't change the graphic position.
        self._sendCommand(b'DP', x, y)


    def drawLine(self, x1, y1, x2, y2):
        # Draw line from (x1, y1) to (x2, y2)
        self._sendCommand(b'LN', x1, y1, x2, y2)


    def drawLineTo(self, x, y):
        # Draw line to (x, y) originating from the current graphic postion.
        self._sendCommand(b'LT', x, y)


    def drawRectangle(self, x, y, w, h, filled = 0):
        # Draw (filled) rectangle. The current graphic position moves to the lower-rigt corner.
        if filled:
            self._sendCommand(b'FR', x, y, x+w, y+h)
        else:
            self._sendCommand(b'DR', x, y, x+w, y+h)


    def drawCircle(self, x, y, r, filled = 0):
        # Draw circle with radius r.
        # This function is affected by foreground color and draw mode, but not affected by
        # line pattern. The current grapch position moves to (x,y).
        self._sendCommand(b'CC', x, y, r, filled)


    def drawImage(self, mode, x, y, w, h, imageData):
        # draws an image at (x, y). Not very useful in this form since it moves all image data over 
        # the stack. See drawImageFile instead.
        if mode == 0:
            self._sendCommand(b'DIM', x, y, w, h, imageData)
        else:
            assert imageData is None or (len(imageData) == mode * w * h), "image data size mismatch"
            self._sendCommand(b'EDIM' + bytes([mode + 48]), ['x', 'y', 'w', 'h', 'imageData'], (), x, y, w, h, imageData)

            
    def drawImageFile(self, mode, x, y, w, h, fileName):
        # see drawImage, only data are read from file, thus saving a lot of memory.
        size = self._getFileSize(fileName)
        assert (size == mode * w * h), "image file data size mismatch"

        # only now send introduction, for open file might fail and then the display keeps waiting for 
        # a load of data (if this happens, keep writing strings until they are diaplayed)
        self.drawImage(mode, x, y, w, h, None)        
        self._sendFile(fileName)

        
    def videoBox(self, x, y, w, h, f, videoData):
        # Video Box (VIDEOxywh/....data) (esc = 61)
        # This command let user to send raw image data to the LCD panel directly, after
        # command "VIDEO", followed by 2 integer data x, y to indicate the top-left position
        # counted as pixels where of the video box, the available value of x,y are from 0
        # to 65535 but not exceed the LCD panel size, then 2 bytes of value to indicate
        # the box width and height, the available value are from 0 to 255.
        # After defined the video box, the next byte of value indicate the color depth of
        # each pixel, if value is 0, the color depth is 16BIT(2 bytes data)
        # NOT tested
        self._sendCommand(b'VIDEO', x, y, w, h, f, videoData)


    def moveArea(self, x, y, w, h, ox, oy):
        # Move area on the screen.
        # Move the area(x,y)-(x+width,y+height) to new top-left position of(x+Ox,y+Oy),
        # the value of Ox, Oy are -127~127.
        # This function is useful to scroll screen in 4 directions.
        self._sendCommand(b'MA', x, y, w, h, ox, oy)


    # --------------------------------------------------------------------------------
    #   Graphic Settings
    # --------------------------------------------------------------------------------

    def setColor(self, c):
        # set the foreground colour.
        if isinstance(c, tuple) or isinstance(c, list):
            self._sendCommand(b'ESC', *tuple(map(lambda x: x>>2, c)))
        else:
            self._sendCommand(b'SC', c)
            
            
    def setBgColor(self, color):
        # Set background color(BGC)  (esc = 53)
        # WARNING: with a light background the display draws more current; if the supply
        #          stalls, it may freeze in an error state.
        self._sendCommand(b'BGC', color)


    def setLineStyle(self, b):
        # Set line pattern.
        # b:  byte indicate which pixel should display or not, there
        # are 8 bits in a byte, so when  drawing line, the module will repeat every 8 bits
        # according to the line pattern value.  eg.: "SLP\x55" command will let the draw
        # line/rectangle function to draw a dotted line, because "\x55" equal: 0B01010101,
        # if the bit is 0, that pixel will not displayed.  If the line pattern value is:
        # 0B11010111, the drawing line is dashed.
        self._sendCommand(b'SLP', b)


    def setOrientation(self, direction):
        # Set screen orientation.
        # The original direction is 0, direction 1,2,3 represent  90,180 and 270 degree clockwise
        self._sendCommand(b'SD', direction)


    def setDrawMode(self, s):
        # Set drawing mode.
        # Command: DM, followed by a byte of draw mode which only one letter can be used
        # from {C,|,!,~,&,^,O,o}. Draw mode is  used to tell the module how to display the
        # color of pixel using current foreground color operating with the existing pixel,
        # there are 6 modes available:  'C'-Copy, doesn't matter the existing pixel on
        # screen, this mode use current foreground color to over _write the pixel,  for
        # "TT" command, it also clear the char box as back ground color, all other modes
        # will not clear the char box.
        self._sendCommand(b'DM', s)


    def setDrawWindow(self, x, y, w, h):
        # Set output/draw window.
        # Draw window was embedded since firmware version 3.2 and later, instead of output
        # to full screen, user can set a smaller rectangle area as draw window, then all
        # following output will be showing in this window and the coordinate also refers
        # to the top-left corner of draw window. This ability provide user a new way to
        # relocate an area of content on the screen to different location easily, just
        # change the draw window to the desired location, then done. Command: DWWIN,
        # follow by top-left coordinate value (x,y), then draw window's width (w) and height (h) all value in
        # pixels.
        self._sendCommand(b'DWWIN', x, y, w, h)


    def resetDrawWindow(self):
        # Reset draw window
        # Cancel drawing mode and reset the coordinate system to the whole screen.
        # tested: OK
        self._sendCommand(b'RSTDW')


    def clearDrawWindow(self):
        # Clear draw window
        # Clear the draw window using background color.
        self._sendCommand(b'WINCL')


    def setImageBackgroundTransparent(self, f):
        # Set image's background transparent
        # When we show an image (256, 65K or 262K color) on the screen, the image occupy a
        # rectangle area, this command can change the image shape on the screen, the black
        # pixels in the rectangle area can be transparent
        self._sendCommand(b'TRANS', f)


    # --------------------------------------------------------------------------------
    #   Monochrome
    # --------------------------------------------------------------------------------

#     def refreshScreenInstantly(self, f):
#         # Refresh screen instantly(FSf)  (esc = 37)
#         # Command: FS, followed by a byte of value 0 or 1. if value is 0, the module will
#         # not refresh the screen until it receive a  fresh screen command such as "FS2",
#         # if the value is 1, the module will refresh the screen from internal screen
#         # buffer  to screen when the module is idle (no more pending commands in receiving
#         # buffer) automatically.  This command only available on Black/White display
#         # module, the color module always refresh the screen instantly  because no screen
#         # buffer used in onboard MCU.  If you need update the screen rapidly, disable the
#         # auto-refresh will help to avoid the screen flicking: draw all  information to
#         # the screen buffer in MCU, the refresh the screen at once.
#         # NOT tested, should work on BW display only
#         self._sendCommand(b'FS', f)


#     def setScreenInverse(self, f):
#         # Set screen Normal/Inverse(INV0/1)  (esc = 40)
#         # Command:INV, follow a byte of value 0 or 1 to indicate the screen content normal
#         # or inverse, this command only  available on some monochrome module, and the
#         # content is affected instantly.
#         # tested: no effect on colour screen, should work on BW display only
#         self._sendCommand(b'INV', f)


    # --------------------------------------------------------------------------------
    #   Command sets
    # --------------------------------------------------------------------------------

    def runCommandSet(self, a):
        # Run command set.
        # Command: FLMCS, followed by 3 bytes of address which indicate the beginning of
        # command set, 3 bytes address format allow the module access all 2MB memory in
        # flash chip.
        # Not tested
        self._sendCommand(b'FLMCS', a)


    # --------------------------------------------------------------------------------
    #   EEPROM utilities
    # --------------------------------------------------------------------------------

    def writeDataToEeprom(self, a, l, data):
        # Write data to EEPROM
        # Command: WREP, followed by 2 bytes of address, 2 bytes of data length (MSB-LSB
        # format), then the data.
        # not tested
        self._sendCommand(b'WREP', a, l, data)


    def readDataFromEeprom(self, a, l):
        # Read data from EEPROM
        # Command: RDEP, followed by 2 bytes of address, 2 bytes of data length (MSB-LSB
        # format), after these 8 bytes of  command sent to the module, the master
        # controller need to wait the data available on the communication port, read  out
        # all desired data from the port.
        # not tested
        self._sendCommand(b'RDEP', a, l)


    # --------------------------------------------------------------------------------
    #   FLASH utilities
    # --------------------------------------------------------------------------------
    # If the flash chip installed onboard, you can use the full 2MB~16MB flash chip to 
    # store welcome screen, user font, command set and user data, all data in flash chip 
    # can be read out. The flash in MCU becomes unusable.
    # If there is no flash chip installed onboard, you can use the 16KB flash, user cannot 
    # read out the data saved in the internal flash memory.
    

    def writeDataToFlash(self, a, l, data):
        # Write data to flash
        # This command applicable to internal 16KB flash or external flash chip. Command:
        # FLMWR, followed by 3 bytes of start address, 3 bytes of data length (MSB, LSB
        # format), then the data. This command can write data to flash chip or internal
        # flash memory.
        # not tested
        self._sendCommand(b'FLMWR', a, l, data)


    def readDataInFlashChip(self, a, l):
        # Read data in flash chip
        # This command only applicable to external flash chip. If the flash chip installed
        # on the board, you can use it to save user data, and read the data when you need
        # it. Command: FLMRD, followed by 3 bytes of address, then 3 bytes of data length,
        # all MSB format. After this command issued, the master controller can read data
        # from the communication port when data in module ready
        # not tested
        self._sendCommand(b'FLMRD', a, l)


    def eraseFlashMemory(self, a, l):
        # Erase flash memory in flash chip
        # This command only applicable to external flash chip.
        # Only writing data to flash chip need this command, this command can erase only
        # specific range of address on all ! color module. Because the erasing on the chip
        # is operating as block, the module will save the useful data in the block to the
        # RAM on screen panel, erase whole block, then restore the useful data back, so,
        # you may see a block of screen at the left-bottom corner show some wild image,
        # that is the data from the erased block
        # not tested
        self._sendCommand(b'FLMER', a, l)


    # --------------------------------------------------------------------------------
    #   Touch panel
    # --------------------------------------------------------------------------------

    def calibrateTouchScreen(self):
        # Calibrate touch screen
        # starts a calibration procedure during which a few points have to be clicked on.
        self._sendCommand(b'TUCHC')


    def readTouchScreen(self):
        # Read touched coordinate
        # Read tousch screen coordinate as sson as it is touched.
        self._sendCommand(b'RPNXYW')
            
            
    def readClick(self):
        # Read touched coordinate
        # Read tousch screen coordinate as sson as it is released.
        self._sendCommand(b'RPNXYC')
    

    def checkTouchScreen(self):
        # Read touch panel instantly
        # The 2 functions above will drive the module frozen until the touch screen pressed. If you 
        # only want to check the touch screen pressed or not, this is the function for the software, 
        # it returns a pair of out of range value of no press on touch screen.
        # You also can check a hardware signal on the module when screen pressed, there is a PENIRQ 
        # signal on the 9pin header, this signal will go low when screen pressed. This is the easiest 
        # way to quote the touch screen if there were a free I/O pin on your master controller.
        # note: a call to this method *also* causes te interrupt to fire.
        self._sendCommand(b'RPNXYI')
    

    def readVoltage(self):
        # Read voltage
        # Connect a voltage on the Vbat pin on the 9pin header, then send command: RDBAT
        # to module, the module will  return 2 bytes of data of voltage on the Vbat pin,
        # MSB format, the unit is mV, the range is 0~10,000. eg.: if the 2 bytes  of value
        # is: 18, 192, the voltage is: 18x256+192=4800mV, is 4.8V.  The input impedance
        # is: 10kO! Hint: if the measured voltage is over 10V, a 2R voltage divider is
        # needed.
        self._sendCommand(b'RDBAT')


    def readAnalog(self):
        # Read analog
        # Connect the analog to the AUX pin on the 9pin header, then use this command to
        # read it, we didn't adjust the 2 bytes result here, the data range is 0~4095, and
        # represent 0~2.5V. Use this format to calculate the real voltage: V=d*2.5/4096.
        # (d is the reading data)
        self._sendCommand(b'RDAUX')


    def readTemperature(self):
        # Read temperature
        # This command read the temperature of the chip, the format to calculate the
        # temperature is: T=(653-(d*2500/4096))/2.1 degree C, d is the reading data. Note,
        # the temperature on the chip may be affected by the backlight heat of LCD screen.
        self._sendCommand(b'RDTMP')


    # --------------------------------------------------------------------------------
    #   Power management
    # --------------------------------------------------------------------------------

    def backlightBrightness(self, percentage):
        # Backlight brightness
        # The backlight brightness on all color LCD and MonoChrome GLCD modules! can be
        # adjusted continuously by use command: BL, followed by a byte of value 0~100, 0
        # will turn backlight full off, and 100 will turn backlight full on. The backlight
        # on all OLED modules are not adjust-able.
        self._sendCommand(b'BL', percentage)


    def turnScreenOn(self, f):
        # Turn screen on
        # Command: SOO, followed by a byte value 0/1, when d=0, the screen and the backlight
        # will be turned off immediately,  that will save much power on the module, this
        # function work on all module.  On most of modules, the module only consume few mA
        # after screen turned off.  The content on the screen unchanged if screen turn off
        # then turn on later.
        # not tested
        self._sendCommand(b'SOO', f)



    def turnMcuOff(self):
        # Turn MCU off(
        # Command: DNMCU, no following data needed, the module will check if there were more 
        # pending commands in buffer before entering sleep. If there were, the module will not 
        # enter sleep mode. The module wakes up automatically when new data are received, but if 
        # the COM mode is I2C, some dummy data are needed to act as waking signal, so, use few 
        # write(0) then a delay 10ms is a good practice to wake up the MCU from deep sleep.
        # The screen will keep on, and all content on the screen unchanged when MCU off.
        # not tested    
        self._sendCommand(b'DNMCU')


    def turnModuleOff(self):
        # Turn module off
        # This command put all power off: backlight off, screen off, MCU enter deep sleep,
        # the module will only consume <0.05mA of current, the wake up sequence is same
        # with wake up MCU, the module will restore backlight and put screen on also after
        # wake up, the content on the screen unchanged.
        self._sendCommand(b'DNALL')


    def turnBackOn(self):
        self._sendCommand(b'\x00\x00\x00\x00')


    # --------------------------------------------------------------------------------
    #   Configuration
    # --------------------------------------------------------------------------------

    def uploadStartScreen(self, fileName):
        # upload start screen to module
        # Command: SSS, followed by 2 bytes of data length of start screen, then the data,
        # as described before, the data  structure are different for monochrome module and
        # color module.  In V3.2 and earlier version on color module, the command set also
        # need 2 bytes of data to indicate the command set  length, when you uploading
        # this format of start screen to module, 2 bytes of length follow to SSS to
        # indicate the  length of rest data, and in the rest of data, the first 2 bytes to
        # indicate the length of command set, their relationship is:  SSS (length+2)
        # (length) (...data...).
        # This function could not be made to work. Can't make sense of what the manual 
        # writes about this (cited here above).
        self._getFileSize(fileName) # file eror, then crash before sending the next command
        self._sendCommand(b'SSS')
        self._sendLargeFileSlowly(fileName)


    def enableStartScreen(self, f):
        # Enable/disable start screen
        # Command: DSS, if the following value is 0, the start screen is not show up on
        # next power on.
        self._sendCommand(b'DSS', f)


#     def setSpiMode(self, mode):
#         # Set SPI mode(SPIMD0~3) (esc = 57)
#         # There are 4 mode for SPI, based on the Clock polarity and phase, the default is
#         # mode 0 (except V3.3, was mode 2). Command: SPIMD, follow a byte to indicate the
#         # new SPI mode, the module will use the new mode on next power up. This command
#         # only available on firmware V3.4 and later.
#         self._sendCommand(b'SPIMD', mode)


    def showConfiguration(self, f):
        # Configuration show on/off
        # In default, the module will show start screen when power on, and also show the
        # current COM mode after start screen showed up, that will tell you what is the
        # Baud on UART mode or the slave address on I2C mode. If you want to manage this
        # configuration show on the screen, use command: DC, then follow by a byte value 0
        # or 1, if d=0, the configuration will not show on the screen on next power on.
        self._sendCommand(b'DC', f)


    def changeI2Caddress(self, b):
        # Change I2C address
        # When you connect multiple modules on a I2C bus, every slave modules MUST be
        # assigned with different address, this function can change the default address of
        # 0x27 to other value. This command only work at I2C COM mode, you can't use it at
        # UART or SPI mode. Command: SI2CA, followed by a byte of new address. The module
        # use the new address instantly, it also save this new address in internal memory,
        # you don't need to change it on the next power recycle.
        # not tested
        self._sendCommand(b'SI2CA', b)


#     def adjustContrast(self, percentage):
#         # Adjust LCD contrast(CTx) (esc = 31)
#         # Command:CT, followed by a byte of value 0~100, this command only effective for
#         # 128*64 GLCD with ST7565 controller, The contrast on GLCD use KS0108 and ST7920
#         # controller only be adjustable by a hardware pot.
#         self._sendCommand(b'CT', percentage)
# 
# 
#     def configUGLCDadapter(self, b1, b2, b3, b4, b5, b6, b7, b8):
#         # Config universal graphic LCD adapter(SLCDx...) (esc = 43)
#         # see manual
#         self._sendCommand(b'SLCD', ((166, 167), (162, 163), (160, 161), (192, 200), (32, 39), (129, 129), (0, 63), (64, 127)), b1, b2, b3, b4, b5, b6, b7, b8)


    # --------------------------------------------------------------------------------
    #   other functions
    # --------------------------------------------------------------------------------


    def delay(self, b):
        # Delay a period
        # This command only available since V3.9, but this is a bug in V3.9: it will be
        # halt if on I2C/SPI mode, fixed in V4.0. Command: "DLY",
        # following with a byte of delay period, value 1 for about 0.25s.
        # not tested
        self._sendCommand(b'DLY', b)


    def sendCommandToScreen(self, b):
        # send command to screen (MCD) (esc = 33)
        # (undocumented, "manualCommand" in arduino-lib)
        # test: causes display to blackout until next power-on
        self._sendCommand(b'MCD', b)


    def sendDataToScreen(self, b):
        # send data to screen (MDT) (esc = 34)
        # (undocumented, "manualData" in arduino-lib)
        # not tested
        self._sendCommand(b'MDT', b)
        
        

class EventCode():
    CLICK   = const(1)
    ANALOG  = const(2)
    TEMP    = const(3)
    VOLTAGE = const(4)
    
    
class DigoleDisplay(DigoleBasic):
    
    def __init__(self, i2cConnection, address):
        super().__init__(i2cConnection, address)
        # add buffers for handling of incoming events:
        self._waitBuffer= []
        self._inBuffer  = []


    def _print(self, *args, end="\r\n"):
        # print to display; syntax like python's print():
        if len(args) == 0: args = [""]
        self.printText(" ".join([str(arg) for arg in args]))
        self.printText(end)

    def printBold(self, v):
        # Prints v as bold face text. Note that this changes the drawmode to OR ('|') 
        self.setDrawMode("|")
        for c in str(v):
            self.printText(c)
            self.returnToLastTextPos()
            self.offsetTextPosition(1,1) 
            self.printText(c)
            self.offsetTextPosition(-1,-1) 
           
    def printUnderlined(self, v):
        # Prints v as underlined text. Note that this changes the drawmode to OR ('|').
        # The underline effect us realized by oversprinting the underscore character.
        # How well this works depends on the selected font. 
        self.setDrawMode("|")
        for c in str(v):
            self.offsetTextPosition(0,1) 
            self.printText("_")
            self.returnToLastTextPos()
            self.offsetTextPosition(0,-1) 
            self.printText(c)
                  
    def cls(self):
        # shorthand name for interactive use
        self.clearScreen()
        
    # redefine read functions to handle responses from the device:    
    def checkTouchScreen(self):
        super().checkTouchScreen()
        self._waitBuffer.append((EventCode.CLICK,   2, getTicks_ms()))

    def readAnalog(self):
        super().readAnalog()
        self._waitBuffer.append((EventCode.ANALOG,  1, getTicks_ms()))
        
    def readClick(self):
        super().readClick()
        self._waitBuffer.append((EventCode.CLICK,   2, getTicks_ms()))
        
    def readTemperature(self):
        super().readTemperature()
        self._waitBuffer.append((EventCode.TEMP,    1, getTicks_ms()))
        
    def readTouchScreen(self):
        super().readTouchScreen()
        self._waitBuffer.append((EventCode.CLICK,   2, getTicks_ms()))
        
    def readVoltage(self):
        super().readVoltage()
        self._waitBuffer.append((EventCode.VOLTAGE, 1, getTicks_ms()))
        
        
    def waitUntilReady(self, timeOut = -1):
        # wait until the device is responsive again
        t = getTicks_ms()
        while True:
            try:
                self._write(b'\00')
                break
            except OSError as e:
                if not "ENODEV" in str(e):
                    raise
                if (timeOut > 0) and (getDeltaTime(t) > timeOut):
                    raise OSError("ETIMEOUT")
                    
                    
    def doCheck(self):
        # function to be called at intervals to detect response events.
        # This is a software implementation that works better than the hardware interrupt penirq
        # (but still not very well).
        try:
            for _ in self._waitBuffer:
                ii = self._readInt() # storing the result into an intermediate variable is 
                self._inBuffer += ii # essential - don't as me why...
            
        except OSError as e:
            if not "ETIMEDOUT" in str(e):
                raise
            
        result = []
        for event_code, argCount, timeStamp in self._waitBuffer:
            if getDeltaTime(timeStamp) > 2000: # 2 sec timeout
                self._waitBuffer.pop(0)
                continue
            
            # check whether reading is lagging behind:
            if len(self._inBuffer) < argCount:
                break
            
            # get args from buffer:
            args = [self._inBuffer.pop(0) for i in range(argCount)]
            
            
            # process individual messages vefore sending on: 
            if (event_code == EventCode.CLICK):
                if (args[0] > 1000):
                    # reject event:
                    continue
            
            if (event_code == EventCode.ANALOG):
                # the real voltage: V=d*2.5/4096. (d is the read value)
                args.insert(0, args[0] * 2.5/4096.)
                
            if (event_code == EventCode.TEMP):
                # T=(653-(d*2500/4096))/2.1 C, d is the read value.
                args.insert(0, (653-(args[0] * 2500./4096.))/2.1)
                
            if (event_code == EventCode.VOLTAGE):
                # 2 bytes of data of voltage on the Vbat pin, MSB format, the unit is mV, the range is 0~10,000.
                pass
                
            result.append((event_code, args))
    
        # if buffers out of sync: reset 'm:
        if (self._waitBuffer == []):
            self._inBuffer = []
    
        return result
    

