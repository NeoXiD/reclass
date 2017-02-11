#
# -*- coding: utf-8 -*-
#
# This file is part of reclass (http://github.com/madduck/reclass)
#
# Copyright © 2007–14 martin f. krafft <madduck@madduck.net>
# Released under the terms of the Artistic Licence 2.0
#

from reclass.utils.dictpath import DictPath
from reclass.defaults import ESCAPE_CHARACTER, \
        PARAMETER_INTERPOLATION_SENTINELS, \
        PARAMETER_INTERPOLATION_DELIMITER
from reclass.errors import IncompleteInterpolationError, \
        InterpolationError, \
        UndefinedVariableError

class RefValue(object):
    r"""
    Isolates references in string values

    RefValue can be used to isolate and eventually expand references to other
    parameters in strings. Those references can then be iterated and rendered
    in the context of a dictionary to resolve those references.

    RefValue always gets constructed from a string, because templating
    — essentially this is what's going on — is necessarily always about
    strings. Therefore, generally, the rendered value of a RefValue instance
    will also be a string.

    Nevertheless, as this might not be desirable, RefValue will return the
    referenced variable without casting it to a string, if the templated
    string contains nothing but the reference itself.

    For instance:

      mydict = {'favcolour': 'yellow', 'answer': 42, 'list': [1,2,3]}
      RefValue('My favourite colour is ${favolour}').render(mydict)
      → 'My favourite colour is yellow'      # a string

      RefValue('The answer is ${answer}').render(mydict)
      → 'The answer is 42'                   # a string

      RefValue('${answer}').render(mydict)
      → 42                                   # an int

      RefValue('${list}').render(mydict)
      → [1,2,3]                              # an list

    The markers used to identify references are set in reclass.defaults, as is
    the default delimiter. If desired, reference expansion can be suppressed by
    escaping the expression with a configurable escape character or pattern,
    also configurable in reclass.defaults. Double-escaping is also supported,
    if the escape character or pattern should be printed without actually
    escaping a reference. If there is nothing to escape after a escape
    character, it gets printed normally.

    For instance (assuming \ as escape character):

      RefValue('\ and \\ will be printed normally.').render(mydict)
      → '\ and \\ will be printed normally.' # a string

      RefValue('\${favcolour} results in ${favcolour}.').render(mydict)
      → '${favcolour} results in yellow.'     # a string

      RefValue('Double-escaped reference: \\${favcolour}').render(mydict)
      → 'Double-escaped reference: \\yellow'  # a string
    """

    # Lexer tokens, using strings for simplified debugging
    LT_ESCAPE = 'ESCAPE'
    LT_INTRPL_START = 'INTRPL_START'
    LT_INTRPL_END = 'INTRPL_END'
    LT_LITERAL = 'LITERAL'

    # Set of escapable lexer tokens
    ESCAPABLE_LT_TOKENS = (LT_ESCAPE, LT_INTRPL_START)

    # Parser part types
    PT_LITERAL = 0
    PT_REFERENCE = 1

    # Token attribute types
    TT_TEXT = 0
    TT_TAG = 1

    # Token expressions
    TOKEN_EXPRS = (
        (ESCAPE_CHARACTER, LT_ESCAPE),
        (PARAMETER_INTERPOLATION_SENTINELS[0], LT_INTRPL_START),
        (PARAMETER_INTERPOLATION_SENTINELS[1], LT_INTRPL_END)
    )

    def __init__(self, string, delim=PARAMETER_INTERPOLATION_DELIMITER):
        self._refs = None
        self._string = string
        self._delim = delim
        self._has_escapes = False
        self._tokens = self._lex(string)
        self._parts = self._parse(self._tokens)
        self.get_references()

    def _lex(self, chars):
        pos = 0
        tokens = []
        token_literal_start = None

        while pos < len(chars):
            # Reset match position variables to -1 (-> no match)
            match_start = match_end = -1

            # Try to find a match from all the configured tokens, which starts
            # at the current lexer position.
            for token_expr in self.TOKEN_EXPRS:
                pattern, tag = token_expr
                match_start = chars.find(pattern, pos, pos + len(pattern))

                if match_start >= 0 and tag:
                    # If a literal was being processed before this match, the literal
                    # should be added to the array of lexed tokens.
                    if token_literal_start is not None:
                        tokens.append((chars[token_literal_start:match_start], self.LT_LITERAL))
                        token_literal_start = None

                    # Calculate the end position of the match and add the tag and text
                    # to the array of lexed tokens.
                    match_end = match_start + len(pattern)
                    text = chars[match_start:match_end]
                    tokens.append((text, tag))
                    break

            if match_start == -1 and token_literal_start is None:
                # If there was no match and no literal is being processed already,
                # set the current position as the start position for the next literal.
                token_literal_start = pos
            elif match_start >= 0:
                # If there was a successful match, we should place the current lexer
                # position to the end of the current match.
                pos = match_end
            else:
                # If there was no match, but a literal is being processed, just increment
                # by one and continue by processing the next character.
                pos += 1

        # If a literal was being processed before the lexer loop ended, it should be
        # added to the token array, otherwise data would get lost.
        if token_literal_start is not None:
            tokens.append((chars[token_literal_start:], self.LT_LITERAL))

        return tokens

    def _parse(self, tokens):
        parts = []
        token_iterator = iter(enumerate(tokens))
        tokens_last_index = len(tokens) - 1

        for index, token in token_iterator:
            if token[self.TT_TAG] == self.LT_LITERAL:
                parts.append({'type': self.PT_LITERAL, 'data': token[self.TT_TEXT]})
            elif token[self.TT_TAG] == self.LT_ESCAPE:
                if index == tokens_last_index:
                    # If the escape token is the last one, just add the token as a literal.
                    parts.append({'type': self.PT_LITERAL, 'data': token[self.TT_TEXT]})
                elif index + 1 <= tokens_last_index \
                        and tokens[index + 1][self.TT_TAG] not in self.ESCAPABLE_LT_TOKENS:
                    # If the escape token is not the last one and the next token is unescapable,
                    # add the escape token normally to the string without skipping it. This
                    # ensures backwards-compatibility to older versions.
                    parts.append({'type': self.PT_LITERAL, 'data': token[self.TT_TEXT]})
                elif index + 2 <= tokens_last_index \
                        and tokens[index + 1][self.TT_TAG] == self.LT_ESCAPE \
                        and tokens[index + 2][self.TT_TAG] not in self.ESCAPABLE_LT_TOKENS:
                    # If the escape token is not the second last one, the next token is another
                    # escape token and the second-next token is unescapable, add both escapes
                    # normally to the string. This ensures backwards-compatibility to older
                    # versions.
                    parts.append({'type': self.PT_LITERAL, 'data': token[self.TT_TEXT]})
                    parts.append({'type': self.PT_LITERAL, 'data': tokens[index + 1][self.TT_TEXT]})
                    token_iterator.next()
                else:
                    # If the escape token is not the last one and the next token is escapable,
                    # add the next token as a literal and skip processing of the next token.
                    # Additionally, set _has_references to True so that we can signal to other
                    # classes that the string still needs to be rendered and can not be just
                    # used as-is to avoid rendering escape tokens.
                    parts.append({'type': self.PT_LITERAL, 'data': tokens[index + 1][self.TT_TEXT]})
                    token_iterator.next()
                    self._has_escapes = True
            elif token[self.TT_TAG] == self.LT_INTRPL_END:
                # Add the interpolation closing tag as a literal, because the loop processing
                # interpolations is done within the interpolation start token parsing.
                parts.append({'type': self.PT_LITERAL, 'data': token[self.TT_TEXT]})
            elif token[self.TT_TAG] == self.LT_INTRPL_START:
                reference_parts = self._parse_interpolation(token_iterator, tokens)
                parts.append({'type': self.PT_REFERENCE, 'data': reference_parts})

        return parts

    def _parse_interpolation(self, token_iterator, tokens):
        parts = []

        # If the end of the interpolation can not be found before
        # the end of our token array, we have to catch the StopException
        # and raise a IncompleteInterpolationError.
        try:
            while True:
                index, token = token_iterator.next()
                if token[self.TT_TAG] == self.LT_INTRPL_END:
                    # Abort the loop if we reached an unescaped interpolation end tag.
                    break
                elif token[self.TT_TAG] == self.LT_ESCAPE:
                    # Do not process escaped interpolation end tags and add them
                    # as a literal to the interpolation reference name instead.
                    if tokens[index + 1] == self.LT_INTRPL_END:
                        parts.append(tokens[index + 1][self.TT_TEXT])
                        token_iterator.next()
                        continue

                # Add all other tokens as a literal to the interpolation reference name.
                parts.append(token[self.TT_TEXT])

        except StopIteration:
            raise IncompleteInterpolationError(''.join(parts), PARAMETER_INTERPOLATION_SENTINELS[1])

        # Check if we have collected any parts at all, otherwise this is an interpolation error.
        if len(parts) == 0:
            raise InterpolationError('String interpolation with empty/zero-length variable' + \
                    'name found.')

        return ''.join(parts)

    def _resolve(self, ref, context):
        path = DictPath(self._delim, ref)
        try:
            return path.get_value(context)
        except KeyError:
            raise UndefinedVariableError(ref)

    def has_escapes(self):
        """Returns a boolean specifying whether the RefValue contains any escaped variable
        references. This is needed as the string needs to be rendered when containing
        actual escapes, otherwise the escape character gets included when it should not."""
        return self._has_escapes

    def has_references(self):
        """Returns a boolean specifying if the RefValue contains unescaped variable references."""
        return len(self.get_references()) > 0

    def get_references(self):
        """Returns an array containing all referenced variable names."""
        if self._refs is None:
            self._refs = [part['data'] for part in self._parts if part['type'] == self.PT_REFERENCE]
        return self._refs

    def _assemble(self, resolver):
        # Just return our actual string when we have got neither references
        # nor escaped references which would require special treatment.
        if not self.has_references() and not self.has_escapes():
            return self._string

        # If the string only contains a reference, the type of the referenced
        # variable should be preserved and not converted to a string.
        if len(self._parts) == 1 and self.has_references():
            return resolver(self._parts[0]['data'])

        # In all other cases, the string has to be assembled piece by piece.
        ret = ''
        for part in self._parts:
            if part['type'] == self.PT_LITERAL:
                ret += part['data']
            elif part['type'] == self.PT_REFERENCE:
                ret += str(resolver(part['data']))

        return ret

    def render(self, context):
        """Renders the RefValue and returns the assembled string. If the string should only contain
        a variable reference, the type of the referenced variable gets preserved."""
        resolver = lambda s: self._resolve(s, context)
        return self._assemble(resolver)

    def __repr__(self):
        do_not_resolve = lambda s: s.join(PARAMETER_INTERPOLATION_SENTINELS)
        return 'RefValue(%r, %r)' % (self._assemble(do_not_resolve),
                                     self._delim)
